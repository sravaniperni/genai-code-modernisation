# releasebot (benchmark fixture)

`releasebot` is a small release-automation toolkit written for this benchmark. It

* parses commit messages that follow Conventional Commits (`releasebot.commits`),
* decides the next semantic version, including pre-releases (`releasebot.versioning`, `releasebot.bumping`,
  built on `semver`),
* relates release tags (plain data exported from git, with per-component prefixes) to versions
  (`releasebot.tags`),
* renders changelog entries and release notes from bundled or user Jinja2 templates
  (`releasebot.templating`, `releasebot.changelog`) with localised dates (`releasebot.dates`) and turns
  release notes into HTML with a Markdown extension that links `#123` and `@user` (`releasebot.notes`),
* reads and updates its YAML configuration with ruamel.yaml (`releasebot.config`),
* converts versions to PEP 440 and checks them against a package index export (`releasebot.pep440`, packaging),
* talks to a Gitea/GitHub-style hosting API with httpx (`releasebot.hosting`),
* publishes releases through built-in and entry-point plugin publishers (`releasebot.plugins`,
  `releasebot.publishers`, importlib-metadata), shell hooks (`releasebot.hooks`) and tarball bundles
  (`releasebot.staging`),
* exposes everything through a click command line (`releasebot.cli`).

The baseline pins old versions of its dependencies (click 7.1.2, semver 2.13.0, packaging 21.3,
Jinja2 3.0.3, Markdown 3.3.7, ruamel.yaml 0.17.21, importlib-metadata 4.13.0, httpx 0.23.3) and genuinely uses
APIs that were removed in the newer releases targeted by the `releasebot-dep-*` tasks. The baseline itself
contains no stdlib deprecations; the `releasebot-mig-*` and `releasebot-bug-*` tasks inject them through
their setup overlays.

Tests never touch the network or real git: HTTP is served by `httpx.MockTransport` (and, in one acceptance
test, a forward proxy on 127.0.0.1), and commit logs/tags are plain data.

## Licence

Original code written for this benchmark. Released under the MIT licence:

Copyright (c) 2026 The benchmark authors

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without
limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the
Software, and to permit persons to whom the Software is furnished to do so, subject to the following
conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions
of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED
TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF
CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
