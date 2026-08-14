#include "ocr_layout.h"

#include <algorithm>
#include <cmath>
#include <cwchar>
#include <cwctype>
#include <numeric>

namespace selectspeak::ocr {
namespace {
enum class BreakKind { Space, Line, Paragraph };

std::wstring Trim(std::wstring text) {
    const auto whitespace = [](wchar_t character) {
        return iswspace(character) != 0;
    };
    const auto first =
        std::find_if_not(text.begin(), text.end(), whitespace);
    const auto last =
        std::find_if_not(text.rbegin(), text.rend(), whitespace).base();
    if (first >= last) {
        return {};
    }
    return {first, last};
}

double Median(std::vector<double> values, double fallback) {
    if (values.empty()) {
        return fallback;
    }
    const auto middle = values.begin() + values.size() / 2;
    std::nth_element(values.begin(), middle, values.end());
    if (values.size() % 2 != 0) {
        return *middle;
    }
    const double upper = *middle;
    const auto lower = std::max_element(values.begin(), middle);
    return (upper + *lower) / 2;
}

bool EndsWithTerminalPunctuation(const std::wstring& text) {
    if (text.empty()) {
        return false;
    }
    std::size_t index = text.size();
    while (index > 0 && (text[index - 1] == L'"' || text[index - 1] == L'\'' ||
                         text[index - 1] == L')' || text[index - 1] == L']' ||
                         text[index - 1] == L'”' || text[index - 1] == L'’')) {
        --index;
    }
    if (index == 0) {
        return false;
    }
    const wchar_t mark = text[index - 1];
    return mark == L'.' || mark == L'?' || mark == L'!' || mark == L':' ||
           mark == L';';
}

bool IsBullet(const std::wstring& text) {
    const std::wstring trimmed = Trim(text);
    if (trimmed.size() >= 2) {
        constexpr wchar_t bullets[] = L"-*+•‣◦▪●";
        if (std::wcschr(bullets, trimmed.front()) != nullptr &&
            iswspace(trimmed[1])) {
            return true;
        }
    }
    std::size_t index = 0;
    while (index < trimmed.size() && iswdigit(trimmed[index])) {
        ++index;
    }
    return index > 0 && index + 1 < trimmed.size() &&
           (trimmed[index] == L'.' || trimmed[index] == L')') &&
           iswspace(trimmed[index + 1]);
}

double HorizontalOverlap(const Bounds& first, const Bounds& second) {
    return std::max(0.0, std::min(first.right(), second.right()) -
                             std::max(first.left, second.left));
}

double BulletContentLeft(const Line& line) {
    if (line.words.size() >= 2) {
        return line.words[1].bounds.left;
    }
    return line.bounds.left + line.bounds.height * 1.25;
}

struct Metrics {
    double line_height;
    double line_gap;
    double content_left;
    double content_right;
    double content_width;
};

Metrics Measure(const std::vector<Line>& lines) {
    std::vector<double> heights;
    double content_left = lines.front().bounds.left;
    double content_right = lines.front().bounds.right();
    for (const auto& line : lines) {
        if (line.bounds.height > 0) {
            heights.push_back(line.bounds.height);
        }
        content_left = std::min(content_left, line.bounds.left);
        content_right = std::max(content_right, line.bounds.right());
    }
    const double line_height = Median(heights, 20.0);

    std::vector<double> gaps;
    for (std::size_t index = 1; index < lines.size(); ++index) {
        const auto& previous = lines[index - 1].bounds;
        const auto& current = lines[index].bounds;
        const double gap = current.top - previous.bottom();
        const double overlap = HorizontalOverlap(previous, current);
        if (gap >= 0 && gap <= line_height * 0.8 && overlap > 0) {
            gaps.push_back(gap);
        }
    }
    const double line_gap = std::min(
        Median(gaps, line_height * 0.25), line_height * 0.55);
    return {
        line_height,
        line_gap,
        content_left,
        content_right,
        std::max(1.0, content_right - content_left),
    };
}

bool LooksLikeHeading(const Line& line, const Line& next,
                      const Metrics& metrics, double gap) {
    const bool larger_text = line.bounds.height > metrics.line_height * 1.18;
    const bool short_text = line.bounds.width < metrics.content_width * 0.68;
    const bool followed_by_body =
        next.bounds.width > line.bounds.width * 1.35 ||
        next.bounds.height < line.bounds.height * 0.9;
    const bool heading_punctuation =
        !EndsWithTerminalPunctuation(line.text) ||
        (!line.text.empty() && line.text.back() == L':');
    return heading_punctuation && followed_by_body &&
           (larger_text ||
            (short_text && gap > metrics.line_gap * 1.35));
}

BreakKind ClassifyBreak(const Line& current, const Line& next,
                        const Metrics& metrics,
                        const std::vector<Line>& lines) {
    const double gap = next.bounds.top - current.bounds.bottom();
    const double left_delta = next.bounds.left - current.bounds.left;
    const double alignment_tolerance = metrics.line_height * 0.65;
    const double paragraph_gap = std::max(
        metrics.line_gap * 1.7, metrics.line_height * 0.8);
    const bool same_left = std::abs(left_delta) <= alignment_tolerance;
    const bool current_bullet = IsBullet(current.text);
    const bool next_bullet = IsBullet(next.text);

    // A vertical reversal normally means Windows has moved to another column.
    if (next.bounds.top < current.bounds.top - metrics.line_height * 0.5) {
        return BreakKind::Paragraph;
    }
    if (gap < -metrics.line_height * 0.45) {
        return BreakKind::Line;
    }
    if (current_bullet) {
        const bool hanging_continuation =
            !next_bullet && gap <= paragraph_gap &&
            std::abs(next.bounds.left - BulletContentLeft(current)) <=
                alignment_tolerance;
        return hanging_continuation ? BreakKind::Space : BreakKind::Line;
    }
    if (next_bullet) {
        return gap > paragraph_gap ? BreakKind::Paragraph : BreakKind::Line;
    }
    if (gap > paragraph_gap) {
        return BreakKind::Paragraph;
    }
    if (LooksLikeHeading(current, next, metrics, gap)) {
        return BreakKind::Paragraph;
    }
    if (left_delta > std::max(metrics.line_height, 14.0)) {
        return BreakKind::Paragraph;
    }

    double local_right = current.bounds.right();
    for (const auto& line : lines) {
        if (std::abs(line.bounds.left - current.bounds.left) <=
            alignment_tolerance) {
            local_right = std::max(local_right, line.bounds.right());
        }
    }
    const double local_width =
        std::max(1.0, local_right - current.bounds.left);
    const double filled_width = current.bounds.width / local_width;
    const bool reaches_wrap_margin = filled_width >= 0.72;
    const bool close_vertical_spacing =
        gap <= std::max(metrics.line_gap * 1.5, metrics.line_height * 0.55);
    if (same_left && reaches_wrap_margin && close_vertical_spacing) {
        return BreakKind::Space;
    }

    // Short aligned rows are more likely labels, list entries, or form fields
    // than wrapped prose. Preserve them for the Python structure normalizer.
    if (same_left && !reaches_wrap_margin) {
        return BreakKind::Line;
    }
    if (EndsWithTerminalPunctuation(current.text) && !same_left) {
        return BreakKind::Line;
    }
    return BreakKind::Space;
}
}  // namespace

std::wstring ReconstructLayout(std::vector<Line> lines) {
    lines.erase(
        std::remove_if(lines.begin(), lines.end(), [](Line& line) {
            line.text = Trim(std::move(line.text));
            return line.text.empty() || line.bounds.width <= 0 ||
                   line.bounds.height <= 0;
        }),
        lines.end());
    if (lines.empty()) {
        return {};
    }

    const Metrics metrics = Measure(lines);
    std::wstring result = lines.front().text;
    for (std::size_t index = 1; index < lines.size(); ++index) {
        switch (ClassifyBreak(lines[index - 1], lines[index], metrics, lines)) {
        case BreakKind::Space:
            result += L' ';
            break;
        case BreakKind::Line:
            result += L'\n';
            break;
        case BreakKind::Paragraph:
            result += L"\n\n";
            break;
        }
        result += lines[index].text;
    }
    return result;
}
}  // namespace selectspeak::ocr
