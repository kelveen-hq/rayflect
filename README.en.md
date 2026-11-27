# Rayflect

*[Version française](README.md)*

## In brief

**What it does.** Rayflect compares low-tech design choices on a building, hour by hour: solar shading, trees and
green walls, openable windows, night ventilation, walls, Trombe walls, geothermal boreholes. It prepares the building
and the occupancy assumptions, then hands the calculation to verified engines (EnergyPlus, through Honeybee and
Ladybug). It returns overheating hours and degree-hours, heating and cooling needs, where heat comes from and where it
goes, daylight, its excess and glare, the carbon of the materials added, and a planting year by year. The same study
can be replayed under a real year, the hottest summer or the climate of the 2040s; `rayflect proposer` starts from the
goals and looks for the measures that meet them.

**What it brings.** Open, checkable reference physics for architects and engineering firms at sketch and early design
stage: every figure carries the proof behind it, and a heavy assumption taken by default states its weight. A tool to
choose, not to certify: it does not replace regulatory calculations.

**Where it stops.** It calculates the building, not a product: a specific device only enters through its hour-by-hour
effect. It does not price any device.

**What it talks to.** It reads a TOML study file, an IFC model, DXF plans, a few figures, or a building in the
"common building" format, version 1 (`io/lecture_batiment_commun.py`, provenance kept field by field). An external
program can give it the effect of a product, hour by hour, in watts (the `apport_horaire` element, a CSV). It returns
`resultats.json`, described by `resultats.schema.json`. It requests its data from public services (PVGIS, IGN and
BD TOPO, Eurostat, Open-Meteo) and keeps them in a cache outside the repository; its carbon factors, read from ADEME's
Base Empreinte and from ICE, are written in the code with their source.

**Language.** The code, the commands and the documentation are in French. This page, the contribution guide and the
issue templates are also in English; questions and contributions are welcome in either language.

## In more detail

**The carbon of what you build counts too.** Each scenario states the carbon of the materials it adds (an aluminium,
timber or concrete overhang, an insulation layer, panels) and in how many years the CO2 it avoids pays it back. The
factors come from public sources and can be changed in the study file, for a low-carbon, reused or bio-based material
(`[carbone]` table, or `carbone_kg` taken from an EPD).

**Start from the need.** Instead of writing the scenarios, you can give your goals (no more than 350 degree-hours,
enough daylight, no more than 5 % extra heating, a carbon ceiling): `rayflect proposer` tries the passive measures of a
palette, alone then combined, and returns those that meet them, with what each one costs on the other criteria.

**A tool to choose, not to certify.** Rayflect gives the order of magnitude of the French RE2020 indicators (discomfort
degree-hours, for example), on the weather and assumptions of the study. It is meant to compare choices at sketch and
early design stage. It never replaces the regulatory calculation, which alone is valid for certification.

**Status: public, under construction.** Everything runs from the command line; there is no interface yet.

To install it and run a first study in 20 minutes: [docs/INSTALLATION.md](docs/INSTALLATION.md) (in French).

## The principle

Rayflect does not recompute building physics. It prepares the building, places the solar shading and the occupancy
assumptions, then hands the calculation to existing, verified engines:

- [EnergyPlus](https://energyplus.net) for heat, air, ground and daylight;
- [Honeybee](https://www.ladybug.tools/honeybee.html) to describe the building;
- [Ladybug](https://www.ladybug.tools) to read the weather and follow the sun's path;
- [IfcOpenShell](https://ifcopenshell.org) to read models;
- [ezdxf](https://ezdxf.mozman.at) to read DXF plans.

## Where the data come from

Rayflect redistributes no data. It requests them from public services, checks them, and keeps them in a cache
outside the repository (`rayflect cache` says where).

| Data | Service | Module |
|---|---|---|
| Typical-year weather, hour by hour, anywhere in Europe | [PVGIS](https://re.jrc.ec.europa.eu/pvg_tools/en/) of the European Commission, through its API | `io/meteo` |
| Location of an address, municipality, altitude | [IGN](https://geoservices.ign.fr) geocoder and altimetry, France | `lieu` |
| Neighbouring buildings and their height | IGN's BD TOPO, France | `environnement` |
| Electricity and gas prices | [Eurostat](https://ec.europa.eu/eurostat) | `energie` |
| Carbon of materials | ADEME's [Base Empreinte](https://base-empreinte.ademe.fr), and ICE V3 cited by the IStructE; to be replaced by an EPD from the [INIES](https://www.base-inies.fr) database | `carbone` |
| A real year, hour by hour, since 1950 | ERA5-Land and ERA5 reanalyses from [Copernicus](https://climate.copernicus.eu), through the [Open-Meteo](https://open-meteo.com) archive API | `io/climats` |
| The climate of 2040 to 2049 | 7 CMIP6 HighResMIP models, through the [Open-Meteo](https://open-meteo.com) climate API | `io/climats` |

A given weather file (`meteo = "file.epw"`) replaces PVGIS: a nearby station, an engineering firm's file. The limits
of a typical year are written in the roadmap, branch 0.

The climate can also be chosen, under the `[lieu]` table: `climat = 2022` (a real year), `"ete_le_plus_chaud"` (the
hottest summer since 2000), `"futur"` (the typical year morphed towards 2040-2049 by Belcher's method, 2005:
temperature, humidity, sun and wind) or `"futur_chaud"` (the hottest summer since 2000, shifted towards 2040-2049: a
real heatwave, in the climate to come). A list, `climat = ["type", "futur", "futur_chaud"]`, plays the same study under
each and compares them: it is under a hot summer and the climate to come that night ventilation, thermal mass and
shading set themselves apart. Open-Meteo data are under the CC BY 4.0 licence, **free for non-commercial use**;
commercial use requires an Open-Meteo subscription. The free API also limits volume per hour: a future climate requests
the daily data of 7 models over 25 years, which uses a large share of it. Each response is cached; if the API refuses,
wait an hour.

## Using it

```bash
rayflect modele my_study.toml     # writes a study file to fill in: model, address, use, scenarios
rayflect etude my_study.toml      # runs the study and compares the scenarios
rayflect etude my_study.toml --climats type,ete_le_plus_chaud,futur    # the same under 3 climates
rayflect proposer my_study.toml   # looks for the measures that meet the study's goals ([objectifs])
rayflect releve building.ifc      # says what was read in the model, and what is missing
rayflect releve ground_floor.dxf --dessin check.svg    # the same from a plan, with a drawing to check by eye
```

A study fits in a TOML file that can be replayed and shared. Its format is described at the top of
`src/rayflect/etude.py`. Each scenario in the file changes the building and is compared with the building as it is:

| A scenario can... | Element type |
|---|---|
| add solar shading | `casquette` (overhang), `joues` (fins), `lames_horizontales`, `lames_verticales`, `lames_saisonnieres`, `lames_pilotees` (louvres), `bso` (external venetian blinds), `balcon` |
| plant | `arbre` (tree), `pergola`, `grimpante` (climber), `mur_vegetal` (planted modules in front of solid walls) |
| change the roof | `toit`, `photovoltaique` |
| change a facade's glazing or the walls | `facade`, and the `[scenario.parois]` table |
| open the windows differently | `ouvrants` |
| change mechanical ventilation | `ventilation` |
| turn a spandrel into a Trombe wall | `mur_trombe` |
| size a geothermal borehole field on its needs | `sondes` |
| receive heat from a calculation made elsewhere | `apport_horaire` |

## What this repository contains

The module list, with the role of each, is in the [French README](README.md#ce-que-contient-ce-dépôt). How it all
fits together, in diagrams, is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); what is not done yet, and how to do it,
is in [docs/FEUILLE_DE_ROUTE.md](docs/FEUILLE_DE_ROUTE.md) (both in French).

`verification/` replays through this chain cases whose result is known elsewhere:

| File | What it replays | Reference | Measured gap |
|---|---|---|---|
| `bestest.py` | 8 cases of the ANSI/ASHRAE 140 standard, 4 of them with an overhang or fins | EnergyPlus on the NREL laboratory models | 0.05 % at most |
| `bestest_nuit.py` | The 4 night ventilation cases (650, 950, 650FF, 950FF) | likewise | 0.03 % at most |
| `bestest_serre.py` | Case 960, the attached sunspace, 2 rooms | likewise | 0.05 % at most |
| `dalle.py` | The 16 slab-on-grade cases, with EnergyPlus's calculated ground | 3 verified numerical solutions | from -2.3 % to +3.5 % depending on the case |
| `ouvrants.py` | Airflow through open windows, single-sided then cross | The formulas of `rayflect.aeration`, recomputed by hand at each time step | 0.2 % at most over the year |
| `reponse_thermique.py` | A thermal response test on a single geothermal borehole, 3 soils | The given soil conductivity, to be found from the slope | from +2.6 % to +3.9 % |
| `trombe_los_alamos.py` | A closed-cavity Trombe wall, Los Alamos test cell, February 1982 | The measured temperatures of both wall faces; the measurements are not in the repository | 1 °C on average, flux through the wall +14 % |

The `ouvrants.py` and `reponse_thermique.py` rows check a set-up against its formula: they do not replace a
measurement. The first 8 cases run with the regular suite; the others with `pytest -m lent`. `prototype/` contains the
end-to-end test scripts.

The standard's weather file is not redistributed here: `verification/reference.py` fetches it from its publisher on
first run and checks its fingerprint.

## Not there yet

- Curtain walls, roof windows and roof shapes when reading models.
- An interface: everything runs through the `rayflect` command.
- A search beyond the palette: `rayflect proposer` tries 9 common passive measures and their combinations, not every
  overhang depth or every insulation.
- Stack airflow between floors, the ventilated cavity of a Trombe wall, the calculated ground under the building in a
  study (it is proven separately, in `verification/dalle.py`).
- Sources for several assumptions, marked `[H]` in the code.
- Point-by-point daylight and the glare of the EN 17037 standard (DGP probability): they require Radiance. EnergyPlus's
  index compares shading devices, not glazing ratios.

## Install and try

The step-by-step guide, from a blank machine to a first results table, is in
[docs/INSTALLATION.md](docs/INSTALLATION.md) (in French). In short, with Python 3.11 or later and EnergyPlus 25.2:

```bash
pip install -e ".[essais,energyplus,maquette]"
```

```bash
rayflect modele my_study.toml
```

```bash
rayflect etude my_study.toml
```

The exact versions of the test machine are in `verrouillage.txt`. Setting up a development machine is described in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Taking part

- **A question, an idea, a study to share:** the [Discussions](https://github.com/kelveen-hq/rayflect/discussions).
- **An error in a result, a crash:** an [issue](https://github.com/kelveen-hq/rayflect/issues/new/choose), with the
  study file that reproduces it.
- **A contribution:** read [CONTRIBUTING.md](CONTRIBUTING.md), then open a pull request.
- **Citing Rayflect** in a report or a paper: [CITATION.cff](CITATION.cff).
- Everyone who takes part follows the [code of conduct](CODE_OF_CONDUCT.md).

What it needs most: architects and engineering firms to test it on real projects.

## Who is behind it

This software is developed by Kelveen, in Bordeaux: [kelveen.com](https://kelveen.com).

## Licence

Copyright (C) 2025-2026 Paul Trément.

Rayflect is free software, distributed under the GNU Affero General Public License, version 3 or later
(AGPL-3.0-or-later). The text is in the `LICENSE` file. It comes with no warranty.

This choice follows from Honeybee, on which Rayflect relies and which is itself under AGPL-3.0. In practice: anyone
may use, study, modify and redistribute Rayflect, provided they redistribute their modifications under the same
licence, including when they offer it as an online service.

The other building blocks: IfcOpenShell is under LGPL-3.0, ezdxf under MIT, Shapely, pvlib and EnergyPlus under
BSD-type licences.
