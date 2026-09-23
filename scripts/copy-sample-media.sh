#!/bin/sh
# Copy LFS-tracked sample media from sampleVideo/ into public/samples/ so
# Next.js can serve it locally. public/samples/*.mp4 is gitignored on purpose;
# hosted deploys point NEXT_PUBLIC_SAMPLES_BASE_URL at a CDN instead.
set -eu

mkdir -p public/samples

copy() {
  src="$1"
  dest="$2"
  [ -s "$src" ] || return 0
  # Skip un-fetched Git LFS pointer files.
  if head -c 12 "$src" | grep -q "^version http"; then
    echo "skip $src (LFS pointer; run: git lfs pull)" >&2
    return 0
  fi
  cp -c "$src" "$dest" 2>/dev/null || cp "$src" "$dest"
}

# Home-page sample keeps its historical public name.
copy sampleVideo/Full_Cooling_Demand_WithAudio_1080p60.mp4 public/samples/cooling-demand.mp4

# Everything else keeps its slug (used by /examples).
for f in sampleVideo/*.mp4; do
  [ -e "$f" ] || continue
  base=$(basename "$f")
  case "$base" in
    Full_Cooling_Demand_WithAudio_1080p60.mp4) continue ;;
  esac
  copy "$f" "public/samples/$base"
done
