#!/bin/sh
# Assemble a portable bundle of the service and the website.
#
#     deploy/make_bundle.sh           # writes dist/ecmwf-widget-<version>-<os>-<arch>.tar.gz
#
# The bundle holds the package with its dependencies already installed, a
# bin/ of launchers (the ingestor, the local widget, the publisher, the
# builder of the static page), the documentation and a starting
# configuration. It runs wherever a python3 of 3.10 or newer exists.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

case "$(uname -s)" in
    Darwin*) OS=macos ;;
    *)       OS=linux ;;
esac
ARCH=$(uname -m)
VERSION=$(python3 -c "import ecmwf_widget; print(ecmwf_widget.__version__)")
STAGE="ecmwf-widget-$VERSION-$OS-$ARCH"
DIST="${DIST:-dist}"

rm -rf "$STAGE" "$DIST" 2>/dev/null || true
mkdir -p "$STAGE/bin" "$DIST"

# The package with its dependencies, ready to run.
python3 -m pip install --quiet --target "$STAGE/vendor" -r requirements.txt .

# One launcher per command. They do not depend on where the bundle lives,
# and they never write outside it: the default database and cache of the
# configuration resolve against the working directory.
write_launcher() {
    cat <<EOG
#!/bin/sh
# $1 - part of the ECMWF widget: $STAGE
DIR=\$(CDPATH= cd -- "\$(dirname -- "\$0")/.." && pwd)
PYTHONPATH="\$DIR/vendor\${PYTHONPATH:+:\$PYTHONPATH}"; export PYTHONPATH
exec python3 -m ecmwf_widget.$2 "\$@"
EOG
}

write_launcher ecmwf-service      service       > "$STAGE/bin/ecmwf-service"
write_launcher ecmwf-widget       widget        > "$STAGE/bin/ecmwf-widget"
write_launcher ecmwf-publisher    auto_publish  > "$STAGE/bin/ecmwf-publisher"
write_launcher ecmwf-publish      publish       > "$STAGE/bin/ecmwf-publish"
write_launcher ecmwf-build-site   build_site    > "$STAGE/bin/ecmwf-build-site"
write_launcher ecmwf-build-places build_places  > "$STAGE/bin/ecmwf-build-places"
write_launcher ecmwf-download     download_9km  > "$STAGE/bin/ecmwf-download"
chmod +x "$STAGE/bin/"*

# The manual, a licence note and a starting configuration, so that
#     cd $STAGE && ./bin/ecmwf-service once && ./bin/ecmwf-widget --open
# works out of the box.
cp README.md "$STAGE/"
cp -R documentation "$STAGE/documentation"
cp places.yml places.pages.yml "$STAGE/"
cat > "$STAGE/README.portable.txt" <<EOF
This bundle was built on $OS ($ARCH), version $VERSION.

    cd $STAGE
    ./bin/ecmwf-service once      # fetch the latest run into ./data
    ./bin/ecmwf-widget --open     # the forecast, on http://localhost:8765

All launchers accept the same options as the repository commands. Edit
places.yml to change the places that are followed.

The software needs python3 >= 3.10 on the PATH. Nothing is written
outside the directory you run it from, except by your own git commands
when the publisher pushes the page it built.
EOF

# Everything into one archive.
tar -czf "$DIST/$STAGE.tar.gz" "$STAGE"
echo "$DIST/$STAGE.tar.gz"
