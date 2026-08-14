# Contributing

> [!IMPORTANT]
> **Code contributions are not currently being accepted,
> as the Python API is not stable yet (version < 1.0.0).**
>
> (This message will be removed as soon as version 1.0.0 is published.)

> [!NOTE]
> All the spaces of the project are governed by the
> [Code of Conduct](https://github.com/pettarin/volumito/blob/main/docs/CODE_OF_CONDUCT.md).


## GitHub Issues

Bug reports, requests for new features, and comments
are handled by creating a new issue in
[GitHub Issues](https://github.com/pettarin/volumito/issues).

- Search the existing issues (both open and closed!)
  before submitting a new issue, to check if your issue has already been
  reported, fixed, or discussed.
- If not, feel free to open a new one.
- If you want to introduce a new feature, please file a GitHub issue first,
  so that the maintainer can discuss
  its purpose/design/implementation with you.
- When reporting a defect, please state the Volumio and `volumito` versions
  you are using, and the steps to reproduce your problem
  (e.g., a code snippet or a sequence of commands, etc.).


## Code Contributions

Before submitting a PR, please make sure:

- You read carefully this document and the
  [DEVELOPMENT](https://github.com/pettarin/volumito/blob/main/docs/DEVELOPMENT.md)
  one.
- You are legally able to and comfortable with applying the current
  [license](https://github.com/pettarin/volumito/blob/main/LICENSE)
  to your code contribution.
- If you used an automated tool (e.g., a LLM/AI tool) to generate it,
  you reviewed and understand the implementation,
  and you took care of removing any unnecessary code (a.k.a., "AI slop").
- You run all the tests with the `make test-all` command as explained in the
  [DEVELOPMENT](https://github.com/pettarin/volumito/blob/main/docs/DEVELOPMENT.md)
  document, and they all pass.
- Your PR is from a fix branch or feature branch (ideally branched off
  a recent state of the `devel` branch), and its target is the `devel` branch,
  following the
  [Branching And Versioning Policy](https://github.com/pettarin/volumito/blob/main/docs/DEVELOPMENT.md#branching-and-versioning-policy).
