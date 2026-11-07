#!/usr/bin/env bash
# h4nb_release.sh: makes a release tag and adds the release to the Spack recipe. See docs/spack.md.
#
# Usage: tools/h4nb_release.sh tag VERSION
#        tools/h4nb_release.sh recipe VERSION
#   VERSION   The release number X.Y.Z, for example 0.1.0. The tag is vX.Y.Z.
#
# Step 1, "tag": the script makes the annotated tag vVERSION on HEAD of the local main branch.
#   It does not push. Push the tag yourself: git push origin main vVERSION
#   GitHub then serves the source archive of the tag.
# Step 2, "recipe": the script downloads the GitHub archive of the tag, calculates its sha256 and
#   adds the line version("VERSION", sha256="...") to the Spack recipe. It commits only the recipe.
#   It does not push. Push the commit yourself: git push origin main
set -euo pipefail

repo_url="https://github.com/EverRest/h4nb"
recipe="spack/spack_repo/h4nb/packages/h4nb/package.py"

die() { echo "h4nb_release: $*" >&2; exit 2; }

[ $# -eq 2 ] || { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
step="$1" version="$2" tag="v$2"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "VERSION must be X.Y.Z (for example 0.1.0), not '$version'"
cd "$(git rev-parse --show-toplevel)"
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || die "check out the branch main first"

case "$step" in
  tag)
    git rev-parse -q --verify "refs/tags/$tag" >/dev/null && die "the tag $tag exists already"
    git diff --cached --quiet || die "the index has staged changes. Commit them or unstage them first"
    if ! git diff --quiet; then
      echo "h4nb_release: warning: the working tree has uncommitted changes. The tag does not include them." >&2
    fi
    git tag -a "$tag" -m "h4nb $version"
    echo "Made the tag $tag on $(git rev-parse --short HEAD)."
    echo "Next: git push origin main $tag"
    echo "Then: make release-recipe VERSION=$version"
    ;;
  recipe)
    git rev-parse -q --verify "refs/tags/$tag" >/dev/null || die "the tag $tag does not exist. Run: make release VERSION=$version"
    grep -q "version(\"$version\"" "$recipe" && die "the recipe has the version $version already"
    git diff --quiet -- "$recipe" && git diff --cached --quiet -- "$recipe" \
      || die "$recipe has uncommitted changes. Commit them first"
    archive_url="$repo_url/archive/refs/tags/$tag.tar.gz"
    tmp="$(mktemp)"
    trap 'rm -f "$tmp"' EXIT
    curl -fsSL -o "$tmp" "$archive_url" || die "cannot download $archive_url. Did you push the tag?"
    if command -v sha256sum >/dev/null; then sum="$(sha256sum "$tmp" | cut -d' ' -f1)"
    else sum="$(shasum -a 256 "$tmp" | cut -d' ' -f1)"; fi
    # Put the new version first, below the line of main. Spack prefers the highest number.
    line="    version(\"$version\", sha256=\"$sum\")"
    awk -v line="$line" '{ print } /^    version\("main", branch="main"\)$/ { print line }' "$recipe" > "$recipe.new"
    grep -qF "$line" "$recipe.new" || { rm -f "$recipe.new"; die "cannot find the line version(\"main\", ...) in $recipe"; }
    mv "$recipe.new" "$recipe"
    git commit -q -m "Add h4nb $version to the Spack recipe" -- "$recipe"
    echo "Added: $line"
    echo "Committed $(git rev-parse --short HEAD). Next: git push origin main"
    ;;
  *) die "unknown step '$step'. Use tag or recipe" ;;
esac
