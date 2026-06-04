#!/bin/bash
# makes recursive symbolic links to the claude skills folder
# can also run this piecewise to install individual skills
cp -srf "${PWD}"/skills/.[^.]* ~/.claude/skills/ # SOURCE must resolve to an absolute path to work
