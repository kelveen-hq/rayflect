# Contributing

*Le guide en français, plus complet, est dans [CONTRIBUER.md](CONTRIBUER.md).*

Thank you for wanting to help. Questions, bug reports, verification cases and code are all welcome, in English or in
French.

## Before writing code

- **A question or an idea:** start a [Discussion](https://github.com/kelveen-hq/rayflect/discussions).
- **A wrong result or a crash:** open an [issue](https://github.com/kelveen-hq/rayflect/issues/new/choose) with the
  study file that reproduces it (without any data you may not share).
- **A larger change:** describe it in a Discussion first, so that we can agree on the approach.

## Setting up

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[essais,energyplus,maquette]"    # Linux and macOS: .venv/bin/python
git config core.hooksPath .githooks
```

Install [EnergyPlus](https://energyplus.net) 25.2 for the calculations. Without it, the tests that need it are skipped
and the rest pass.

## Before proposing a change

```bash
python -m ruff check .
python -m pytest                    # the regular suite, about 4 minutes with EnergyPlus
python -m pytest -m lent            # also, when the calculation, zoning or shapes are touched
```

## The house rules

1. **Do not recompute the physics.** Thermal and daylight calculations are EnergyPlus's. This repository prepares the
   building, places the shading and reads the result. A home-made calculation is kept only if it is fast and its gap
   to EnergyPlus is measured and written down.
2. **Every value says where it comes from.** `[S]` sourced (the source is cited), `[D]` derived from a sourced value,
   `[H]` assumption to be replaced, `[C]` cited second-hand. A value without a mark is refused.
3. **What is missing is asked for.** Data missing from the model goes into the "to ask" list; it is never guessed
   silently.
4. **A measured pitfall is written where it bites.** When an EnergyPlus setting or a file format has been misleading,
   the comment says what was measured, next to the code that avoids it.
5. **One test per behaviour**, named after what it proves. Tests do not go out on the network.
6. **Data are not redistributed from here.** Models, weather files and calculation outputs stay outside the
   repository; downloads go into the cache (`rayflect cache` says where).

The code, its comments and the documentation are in French: write in French if you can, in English otherwise; we will
help.

## Licence

The repository is under AGPL-3.0-or-later, like Honeybee on which it depends. Every contribution is received under this
licence. By contributing, you also follow the [code of conduct](CODE_OF_CONDUCT.md).
