# Terminal experience

## Name

> **Uncle Matt's Project Manageroo**

Run it:

> **manageroo**

Full incredibly super serious acronym:

> **MANAGEROO**

## Animation

The installer and `manageroo banner` use hand-authored MANAGEROO ANSI artwork. No font package or terminal graphics dependency is installed.

When color and animation are available, the banner prints an italic moving-rainbow line under the name tag: "Offload your thinking so you can really do some thinking..."

Animation disables automatically when output is not a TTY, `CI` is set, `TERM=dumb`, `NO_COLOR` is set, or `MANAGEROO_ANIMATION=0` is set.

## Music

The soundtrack is original and generated from code at runtime. No browser, MP3 bundle, audio framework, or permanent music file is installed.

The synthesizer uses square-wave lead, triangle-wave bass, deterministic noise percussion, and fixed original patterns. The install cue is about five minutes long, with changing sections instead of one tiny loop repeated forever.

Every generated cue has a three-second fade in and a three-second fade out.

Music playback is best-effort and never required for success. The installer uses the first available local audio player it can find and continues silently when no player is available.

Commands:

```bash
manageroo music --cue install --variant 69
manageroo music --cue build --variant 69
manageroo music --cue success --variant 69
```

Disable globally:

```bash
export MANAGEROO_MUSIC=0
```
