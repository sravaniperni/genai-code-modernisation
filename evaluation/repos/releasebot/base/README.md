# releasebot

Release automation for repositories that follow [Conventional Commits](https://www.conventionalcommits.org/).

releasebot reads the commit log and the existing release tags, decides the next semantic version,
renders a changelog entry and release notes, and hands the release to publishers (changelog file,
code-hosting release, HTML notes, shell hooks, release bundle, or third-party plugins).

```
releasebot --config .releasebot.yml next --log commits.json --tags tags.json
releasebot changelog --log commits.json --tags tags.json
releasebot publish --log commits.json --tags tags.json --publisher changelog --publisher hosting
```

Commit logs and tags are passed as JSON exported from git (`sha`, `message`, `timestamp`, `author`
for commits; `name`, `sha`, `timestamp` for tags), so releasebot itself never shells out to git.

## Development

```
pip install -r requirements.txt -r requirements-dev.txt
pytest
```
