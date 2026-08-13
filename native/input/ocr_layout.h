#pragma once

#include <string>
#include <vector>

namespace selectspeak::ocr {
struct Bounds {
    double left = 0;
    double top = 0;
    double width = 0;
    double height = 0;

    double right() const { return left + width; }
    double bottom() const { return top + height; }
};

struct Word {
    std::wstring text;
    Bounds bounds;
};

struct Line {
    std::wstring text;
    Bounds bounds;
    std::vector<Word> words;
};

std::wstring ReconstructLayout(std::vector<Line> lines);
}  // namespace selectspeak::ocr
