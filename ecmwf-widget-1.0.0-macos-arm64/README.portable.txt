This bundle was built on macos (arm64), version 1.0.0.

    cd ecmwf-widget-1.0.0-macos-arm64
    ./bin/ecmwf-service once      # fetch the latest run into ./data
    ./bin/ecmwf-widget --open     # the forecast, on http://localhost:8765

All launchers accept the same options as the repository commands. Edit
places.yml to change the places that are followed.

The software needs python3 >= 3.10 on the PATH. Nothing is written
outside the directory you run it from, except by your own git commands
when the publisher pushes the page it built.
