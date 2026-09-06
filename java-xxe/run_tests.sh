#!/usr/bin/env bash
# Compile both readers and run the corpus through each.
#
# No build tool and no test framework: the JDK is the only dependency, so this
# runs anywhere a JDK is on PATH. Set JAVA_HOME to point at a specific one.
set -eu

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

if [ -n "${JAVA_HOME:-}" ]; then
    javac="$JAVA_HOME/bin/javac"
    java="$JAVA_HOME/bin/java"
else
    javac="$(command -v javac)"
    java="$(command -v java)"
fi

if [ ! -x "$javac" ]; then
    echo "no javac found; set JAVA_HOME or put a JDK on PATH" >&2
    exit 2
fi

"$javac" --version
rm -rf build
mkdir -p build
"$javac" -Xlint:all -d build src/*.java
"$java" -cp build Harness cases
