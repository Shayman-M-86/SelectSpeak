#include "ocr_layout.h"

#include <cstdlib>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

using selectspeak::ocr::Bounds;
using selectspeak::ocr::Line;
using selectspeak::ocr::ReconstructLayout;
using selectspeak::ocr::Word;

namespace {
Line MakeLine(std::wstring text, double left, double top, double width,
              double height) {
    return {std::move(text), {left, top, width, height}, {}};
}

Line MakeBullet(std::wstring text, double top) {
    return {
        std::move(text),
        {0, top, 420, 20},
        {
            {L"•", {0, top, 10, 20}},
            {L"Item", {24, top, 396, 20}},
        },
    };
}

void Expect(const char* name, const std::vector<Line>& lines,
            const std::wstring& expected) {
    const std::wstring actual = ReconstructLayout(lines);
    if (actual != expected) {
        std::wcerr << L"FAILED " << name << L"\nExpected: [" << expected
                   << L"]\nActual:   [" << actual << L"]\n";
        std::exit(1);
    }
}
}  // namespace

int main() {
    Expect(
        "visual wraps",
        {
            MakeLine(L"This is a perfectly ordinary sentence that", 0, 0,
                     500, 20),
            MakeLine(L"wraps because the window is narrow and", 0, 25, 500,
                     20),
            MakeLine(L"continues onto a final visual line.", 0, 50, 300, 20),
        },
        L"This is a perfectly ordinary sentence that wraps because the window "
        L"is narrow and continues onto a final visual line.");

    Expect(
        "paragraph gap",
        {
            MakeLine(L"The first paragraph wraps onto", 0, 0, 500, 20),
            MakeLine(L"a second visual line.", 0, 25, 260, 20),
            MakeLine(L"A new paragraph starts here.", 0, 82, 350, 20),
        },
        L"The first paragraph wraps onto a second visual line.\n\n"
        L"A new paragraph starts here.");

    Expect(
        "heading",
        {
            MakeLine(L"Important Findings", 0, 0, 230, 30),
            MakeLine(L"Inflammation was present and the body text", 0, 48, 520,
                     20),
            MakeLine(L"continues on another visual line.", 0, 73, 360, 20),
        },
        L"Important Findings\n\nInflammation was present and the body text "
        L"continues on another visual line.");

    Line continuation =
        MakeLine(L"continues on a wrapped line", 24, 25, 360, 20);
    Expect(
        "bullets and hanging indent",
        {
            MakeBullet(L"• First item that", 0),
            continuation,
            MakeBullet(L"• Second item", 50),
        },
        L"• First item that continues on a wrapped line\n• Second item");

    Expect(
        "indented paragraph",
        {
            MakeLine(L"The existing paragraph ends here.", 0, 0, 500, 20),
            MakeLine(L"An indented paragraph starts here.", 40, 25, 380, 20),
        },
        L"The existing paragraph ends here.\n\n"
        L"An indented paragraph starts here.");

    Expect(
        "short structural rows",
        {
            MakeLine(L"Name", 0, 0, 80, 20),
            MakeLine(L"Address", 0, 25, 110, 20),
            MakeLine(L"Phone", 0, 50, 90, 20),
            MakeLine(L"A deliberately wide value establishes the layout width",
                     0, 75, 520, 20),
        },
        L"Name\nAddress\nPhone\nA deliberately wide value establishes the "
        L"layout width");

    Expect(
        "column change",
        {
            MakeLine(L"Left column first line continues", 0, 0, 300, 20),
            MakeLine(L"onto its second line.", 0, 25, 200, 20),
            MakeLine(L"Right column starts here", 380, 0, 260, 20),
            MakeLine(L"and continues here.", 380, 25, 220, 20),
        },
        L"Left column first line continues onto its second line.\n\n"
        L"Right column starts here and continues here.");

    std::cout << "OCR layout tests passed\n";
    return 0;
}
