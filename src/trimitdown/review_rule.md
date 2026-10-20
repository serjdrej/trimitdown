# Reviewing pages prepared by trimitdown

trimitdown converted a PDF and found pages whose text it cannot vouch for: scans,
OCR layers nobody has checked, text layers every decoder reads as garbage. This
directory hands those pages to you. The code does not review anything itself;
this file is the procedure. It is built on a measured procedure (OCR first, then
reconcile against the page image and correct only the differences), which beat
both bare OCR and transcription from the image on every sample it was measured
on.

## What is here

| file | what it is |
|---|---|
| `manifest.json` | every page: its path, why, its image and candidate, OCR status, metrics |
| `document.md` | the converted document; `<!-- page N -->` marks where each page starts |
| `pages/pNNNN.png` (or `.jpg`) | the image of each page to review |
| `candidates/pNNNN.txt` | the candidate text of that page; may be empty |
| `reviewed/` | **the only place you write** |

Pages to review are the ones with `"review": true` in the manifest. Write only
those. If your own procedure writes every page, a page that was not sent may
appear as its header line alone; it is ignored. Text for such a page is refused:
it comes from the PDF's own layer. Page numbers count from 1, from the start of
the PDF, everywhere.

## Before you start

1. **Name the volume and the price, then start.** The measured cost is about
   $0.04 per page (Sonnet, medium effort, OCR plus reconciliation); the
   manifest's `summary` gives the number of pages. It grows faster than linearly
   on long documents, because every page adds to a context that each later turn
   re-reads. **Split the work into chunks of 10-20 pages per subagent.**
2. **Model.** Measured: Sonnet at medium effort. High effort and Opus did not add
   accuracy for the price; Haiku inserted words that are not on the page and
   dropped content.
3. **Write only into `reviewed/`.** In the measurement 3 runs out of 8 wrote a
   helper script outside their directory although told not to. If the boundary
   matters (client documents), it has to be enforced by the environment, not by
   this text.

## Each page

1. **Orientation first.** Look at the image before the candidate. If the page
   lies on its side, the manifest says so in `ocr.orientation` when it could
   tell. A sideways page OCRs to noise: transcribe it from the image, and say so
   in the receipt.
2. **The candidate is a hypothesis about the page, not the page.** Its `source`
   in the manifest says where it came from: `tesseract` (fresh OCR), `ocr_layer`
   (an OCR layer already inside the PDF, made by someone else's software, never
   checked), or nothing.
3. **Correct only the differences.** Open the image, compare it with the
   candidate, fix the words and the digits where they differ. **Do not retype a
   page that has a candidate.** A retyped page comes back smoothly "corrected":
   a grammatically better word that is not on the page, measured in two runs out
   of two.
4. **An empty candidate** means there was nothing to start from: no Tesseract,
   no language data, or a page OCR could not read. Then you transcribe from the
   image. It costs more and it is where the smooth errors come from, so be
   literal, and record the method per page in the receipt.
5. **Digits are not the only thing OCR swaps.** It reads letters as digits as
   well: `б)` as `6)`, `о` as `0`. A digits-only pass leaves those in.

## Where reconciliation goes wrong

- **Long codes** (signature and certificate identifiers, VIN, budget codes,
  power-of-attorney numbers): at the size you read the page, characters merge.
  Check them on a crop at full resolution (`trimitdown render` writes 300 dpi
  images; if the `trimitdown` command is not on PATH, `python -m trimitdown
  render` is the same command). If you cannot make a crop at all, do not read
  the code off the reduced page: write `{{CODE_UNSURE}}`.
- **Text under a stamp or a seal**: do not restore it from neighbouring pages.
  Write `{{ILLEGIBLE}}`.
- **Tables**: if OCR shuffled the cells, rewrite the table from the image row by
  row, cells separated by ` | `. This is the one place where retyping is the
  right thing.
- **Two columns side by side** (parties' details, signatures): check that OCR
  did not merge their lines.
- **Mixed alphabets**: a Latin letter inside a Cyrillic word is invisible to the
  eye and breaks search. Check the result for it; the manifest's
  `latin_in_cyr_words` and `mixed_script_words` count it in the candidate.

## What to write

Either one file for the document, `reviewed/doc.txt`, where each reviewed page
starts with the line

    {{PAGE_HEADER}}

or one file per page, `reviewed/pNNNN.txt` (same four-digit number as the
image). Not both for the same page. Only pages marked for review.

In the text:

- lines as on the image; a word hyphenated at the end of a line stays so;
- superscript as `^`: `87^1`;
- unreadable: `{{ILLEGIBLE}}` in place of the word; doubtful reading:
  `{{UNSURE}}` -- do not guess;
- handwriting `{{HANDWRITTEN}}`; signature `{{SIGNATURE}}`, seal `{{SEAL}}`,
  stamp `{{STAMP}}`;
- running heads and page numbers as on the image;
- **correct nothing in the original**, not even an obvious typo; add nothing;
- **the image wins over grammar.** Do not change a word ending, a case or an
  agreement because the sentence seems to want another one: if the image reads
  `лицом` where grammar suggests `лицам`, write `лицом`. In a measured run a
  reviewer did exactly this, unmarked, and it was the one error of the run;
- an empty page: the header line only.

Also write:

- `reviewed/corrections.tsv`: one line per corrected word,
  `page<TAB>was<TAB>now`;
- `reviewed/receipt.txt`, the coverage receipt, four lines:

```
{{RECEIPT}}
```

## Putting it back

    trimitdown assemble <this directory> -o document.md

puts each reviewed page in place of its marker in `document.md`, keeps the
`<!-- page N -->` line at the start of every page so the result can be cited by
page (`--no-page-anchors` drops it), and refuses, with a message, text for a page
that was not sent for review or a page that appears twice.
Pages left unreviewed make it stop and list them; `--allow-missing` keeps
their unverified text and markers instead.

## Pages that were not sent here

Pages on the `accept` and `substitute` paths come from the PDF's own text
layer, which decoded cleanly. Readable text does not prove the digits are
right: where a conclusion rests on a number (article, part, item, date, sum),
check it against the image -- that is a separate pass.

    trimitdown render <file.pdf> --pages 5,7 -o <dir>

writes those page images without converting anything.
