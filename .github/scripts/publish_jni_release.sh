#!/usr/bin/env bash
# Run from the verified artifact directory. Publication is community-only until full qualification.
set -euo pipefail
: "${GH_REPO:?GH_REPO is required}"
: "${SOURCE_SHA:?SOURCE_SHA is required}"
[[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo 'SOURCE_SHA must be a complete commit hash' >&2
  exit 1
}
if [ "${NATIVE_FEATURES:-community}" != community ]; then
  echo 'Full artifacts are experimental; Maven/release publication awaits full qualification' >&2
  exit 1
fi
sha256sum --check --strict ./*.sha256
tag="jni-${SOURCE_SHA}"
if gh release view "$tag" >/dev/null 2>&1; then
  echo "Release $tag already exists; refusing to replace its JNI payload" >&2
  exit 1
fi

# --verify-tag checks existence, not the commit. Peel annotated tags before publishing.
object="$(gh api "repos/${GH_REPO}/git/ref/tags/${tag}")"
for ((depth = 0; depth < 8; depth++)); do
  object_type="$(jq -er '.object.type | strings' <<< "$object")"
  object_sha="$(jq -er '.object.sha | strings' <<< "$object")"
  [[ "$object_sha" =~ ^[0-9a-f]{40}$ ]] || {
    echo "Invalid object in release tag $tag" >&2
    exit 1
  }
  if [ "$object_type" = commit ]; then
    break
  fi
  if [ "$object_type" != tag ]; then
    echo "Release tag $tag must resolve to a commit" >&2
    exit 1
  fi
  object="$(gh api "repos/${GH_REPO}/git/tags/${object_sha}")"
done
if [ "$object_type" != commit ] || [ "$object_sha" != "$SOURCE_SHA" ]; then
  echo "Release tag $tag resolves to $object_sha ($object_type), expected $SOURCE_SHA" >&2
  exit 1
fi
gh release create "$tag" --verify-tag --target "$SOURCE_SHA" \
  --title "Topling JNI ${SOURCE_SHA:0:12} (Linux amd64)" \
  --notes-file build-info.txt --latest=false \
  ./*.jar ./*.sha256 build-info.txt
