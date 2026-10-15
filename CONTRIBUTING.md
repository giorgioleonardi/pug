# Contributing

- **Changes:** open a pull request (from a fork or a branch). Please don't push directly to `main`.
- **Bugs or ideas:** open an issue.

## Development setup

```bash
git clone https://github.com/giorgioleonardi/pug.git
cd pug
python3 -m venv venv && source venv/bin/activate
pip install -e . -r requirements-dev.txt
```

Go is needed for the tests that build the generated CLI (they skip if `go` isn't on your PATH).

## Tests

```bash
pytest -m "not network and not anthropic"   # offline: no internet, no Anthropic key
pytest -m "network and not anthropic"       # also calls jsonplaceholder.typicode.com
```

Tests marked `anthropic` send a request to the Anthropic API (with a fake key) and are never run in CI.

CI (GitHub Actions) runs on every pull request: the offline tests on Python 3.10, 3.12 and 3.13, plus a non-blocking network job.

Thanks.
