# Bundled lyric preview assets

JavascriptSubtitlesOctopus / libass-wasm **4.1.0**, retrieved 2026-09-06.
Official project: https://github.com/libass/JavascriptSubtitlesOctopus
Package: https://registry.npmjs.org/libass-wasm/-/libass-wasm-4.1.0.tgz
The npm tarball SHA-512 was checked against the registry integrity value:

`sha512-+RbYT/uuI6VHExCmGyUuMg3A2gQOaCRTzSn8GGDSf3q4cEoUNiINd9u4RGfZXA1UKafW+Hv8bmcKIX4FKbSh0Q==`

The main JS, Web Worker and WASM are unmodified package files. LICENSE and
COPYRIGHT accompany them. The host provides a separate worker bootstrap with
an explicit WASM URL; it does not patch these assets or fetch a CDN at runtime.

Noto Sans Regular, Bold, Italic and BoldItalic are from the official notofonts/noto-fonts repository:
https://github.com/notofonts/noto-fonts/tree/main/hinted/ttf/NotoSans
Retrieved 2026-09-06; the upstream license is retained as NOTO-LICENSE.
The browser and FFmpeg use these same four font files. Hashes pin the actual
retrieved bytes independently of the upstream main branch.

| File | SHA-256 |
|---|---|
| COPYRIGHT | `1272d301a909929c5ba3e64f54f208f07f93b1764dbee783e180a8d296923e79` |
| LICENSE | `352fbab9abdf49eff4cb1bb010fe307022dc3f05a4d821afe1d2ebdc0e3db10e` |
| NOTO-LICENSE | `0dab92d0544f7b233403f14b84a663bdbfa746982eda629e7f4f9ffe1b036feb` |
| NotoSans-Bold.ttf | `c976e4b1b99edc88775377fcc21692ca4bfa46b6d6ca6522bfda505b28ff9d6a` |
| NotoSans-Regular.ttf | `b85c38ecea8a7cfb39c24e395a4007474fa5a4fc864f6ee33309eb4948d232d5` |
| NotoSans-Italic.ttf | `36cff144df01309dab648bea71baff9bb074026914afe63aeacc8bc90b67a28b` |
| NotoSans-BoldItalic.ttf | `6edf4227ef0fa846aca70e86a307804ca4401741830f5b3af0f2554abe2b8466` |
| subtitles-octopus-worker.js | `f95f2186c6ea37701cd2badb65568d3e501404deaab7e8460722435cd37f8d56` |
| subtitles-octopus-worker.wasm | `62892886b4a75dbc6a92e12fcd794c7ddaf95f395e09d4a75612c572612f42a9` |
| subtitles-octopus.js | `34529687bafd19622763e0cc57749c51d64d47dd898ad898f48ce502cb89f25b` |
