#!/usr/bin/env bash
# ================================================================
#  NTCDG Full Deck Test — Illuminati Art Deco
#
#  Black & white, graphical, minimal geometry, halftone textures,
#  art deco linework, illuminati symbolism.
#
#  Estimated: ~160 text calls + ~81 images ≈ $2.50–$3.00
#  Time: ~15–20 minutes
# ================================================================
set -euo pipefail

DECK_NAME="Illuminati_Deco"

VIBE="stark black and white art deco, bold geometric shapes, \
heavy halftone dot patterns, high-contrast ink illustration, \
minimal clean linework, sacred geometry, secret society symbolism, \
1920s propaganda poster aesthetic with occult undertones"

DECK_PROMPT="A tarot deck channeling the visual language of \
early 20th century art deco design fused with illuminati and \
secret society iconography. Every card features stark black ink \
on white, built from pure geometric primitives — triangles, \
circles, radiating lines, and all-seeing eyes. Halftone dot \
gradients replace traditional shading. The aesthetic is a \
forbidden blueprint discovered in a Masonic archive: precise, \
graphic, and deeply symbolic."

NEGATIVE_PROMPT="color, colorful, painterly, soft, blurry, \
realistic, photographic, gradients, watercolor, pastel, \
busy backgrounds, cluttered, text, words, letters"

IMAGE_SIZE="1024x1792"

BACK_PROMPT="Stark black and white art deco sacred geometry mandala, \
all-seeing eye at center surrounded by radiating triangles and \
concentric circles, heavy halftone dot textures, 1920s occult \
blueprint aesthetic, no text, no borders"

echo "================================================================"
echo "  NTCDG Full Deck Test: ${DECK_NAME}"
echo "================================================================"
echo ""
echo "  Vibe:    ${VIBE:0:70}..."
echo "  Cards:   78 (full deck)"
echo "  Symbols: AI-generated"
echo "  Images:  ${IMAGE_SIZE}"
echo ""

# ── Pre-flight: estimate cost ──
echo "── Estimating cost ──"
ntcdg --deck \
  --name _cost_check \
  --cards 1 \
  --vibe "test" \
  --no-interactive \
  --no-preview 2>/dev/null || true
echo "Estimated: ~160 API calls, ~\$2.50-\$3.00, ~15-20 min"
echo ""

# ── Confirm ──
read -rp "Proceed with full generation? [y/N] " confirm
if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "── Starting generation ──"
START_TIME=$(date +%s)

ntcdg --deck \
  --name "${DECK_NAME}" \
  --cards 78 \
  --vibe "${VIBE}" \
  --deck-prompt "${DECK_PROMPT}" \
  --analyze \
  --generate-images \
  --symbol-mode generate \
  --image-size "${IMAGE_SIZE}" \
  --negative-prompt "${NEGATIVE_PROMPT}" \
  --no-interactive

END_TIME=$(date +%s)
ELAPSED=$(( END_TIME - START_TIME ))
MINS=$(( ELAPSED / 60 ))
SECS=$(( ELAPSED % 60 ))

echo ""
echo "── Generation complete: ${MINS}m ${SECS}s ──"
echo ""

# ── Status check ──
echo "── Deck status ──"
ntcdg --deck-info "${DECK_NAME}"
echo ""

echo "── Card list ──"
ntcdg --list-cards "${DECK_NAME}"
echo ""

echo "── Usage stats ──"
ntcdg --deck-stats "${DECK_NAME}"
echo ""

# ── Retry any failures ──
ERRORS=$(ntcdg --list-cards "${DECK_NAME}" 2>/dev/null | grep -c "ERR\|MISS" || true)
if [[ "${ERRORS}" -gt 0 ]]; then
    echo "── Retrying ${ERRORS} failed cards ──"
    ntcdg --retry-failed "${DECK_NAME}" \
      --no-interactive
    echo ""
fi

# ── Generate card back ──
echo "── Generating card back ──"
ntcdg --set-back "${DECK_NAME}" \
  --back-prompt "${BACK_PROMPT}"
echo ""

# ── Finalize ──
echo "── Finalizing (PDFs + booklet) ──"
ntcdg --finalize "${DECK_NAME}" \
  --sheet-size letter \
  --color-mode bw
echo ""

# ── Export ──
echo "── Exporting bundle ──"
ntcdg --export "${DECK_NAME}"
echo ""

# ── Final report ──
echo "================================================================"
echo "  TEST COMPLETE: ${DECK_NAME}"
echo "================================================================"
echo ""
echo "  Time:     ${MINS}m ${SECS}s"
echo "  Images:   generated_decks/images/${DECK_NAME}_*.png"
echo "  Back:     generated_decks/images/${DECK_NAME}_BACK.png"
echo "  PDFs:     generated_decks/${DECK_NAME}_PRINT_*.pdf"
echo "  Booklet:  generated_decks/${DECK_NAME}_BOOKLET.pdf"
echo "  Bundle:   generated_decks/${DECK_NAME}_BUNDLE.zip"
echo ""
ntcdg --deck-stats "${DECK_NAME}"
echo "================================================================"
