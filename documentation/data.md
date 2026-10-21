# The data

Everything comes from ECMWF's free and open data. There is no account, no
API key and no registration of any kind.

## Where it comes from

| | |
| --- | --- |
| The portal | <https://data.ecmwf.int/forecasts> |
| The dataset page | <https://www.ecmwf.int/en/forecasts/datasets/open-data> |
| The official documentation | [ECMWF open data: real-time forecasts from IFS and AIFS](https://confluence.ecmwf.int/spaces/DAC/pages/272310539/ECMWF+open+data+real-time+forecasts+from+IFS+and+AIFS) |
| The licence | [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/) |
| The parameter database | <https://apps.ecmwf.int/codes/grib/param-db/> |
| The charts | <https://charts.ecmwf.int/> |

The same data is mirrored in the clouds, and this project falls back to them
when the portal is slow:

| Mirror | Where |
| --- | --- |
| AWS | [registry.opendata.aws/ecmwf-forecasts](https://registry.opendata.aws/ecmwf-forecasts/) |
| Microsoft Azure | [planetarycomputer.microsoft.com/dataset/ecmwf-forecast](https://planetarycomputer.microsoft.com/dataset/ecmwf-forecast/) |
| Google Cloud | [BigQuery public dataset](https://console.cloud.google.com/marketplace/product/bigquery-public-data/open-data-ecmwf/) |

There is also an official Python package, [`ecmwf-opendata`](https://github.com/ecmwf/ecmwf-opendata),
which speaks the same protocol. This project does its own downloads so that
it can control exactly which byte ranges are transferred.

## The models

Three models are published, and they are not the same length.

| Key | Model | Grid | How far it reaches |
| --- | --- | --- | --- |
| `ifs` | IFS, the deterministic forecast | 0.1° (about 9 km) | 360 h for the 00 and 12 UTC runs, 144 h for the 06 and 18 UTC runs |
| `ifs025` | The same forecast, coarser | 0.25° | as above |
| `aifs` | AIFS, the artificial intelligence forecast | 0.25° | 360 h for every run |
| `aifs_ens` | The AIFS ensemble | 0.25° | 360 h |

This is not a detail of the implementation, it is how ECMWF publishes them:
the 00 and 12 UTC runs carry the long range, the 06 and 18 UTC runs are short
and fresh. The widget therefore shows the run that reaches furthest by
default, and the run selector says where each one ends.

More detail is in
[What's new at 0.1°](https://confluence.ecmwf.int/spaces/DAC/pages/738041087/ECMWF+open+data+what+s+new+at+0.1%C2%B0)
and in
[the AIFS pages](https://confluence.ecmwf.int/spaces/DAC/pages/738041086/ECMWF+open+data+AIFS+machine-learning+data).

## The parameters

48 surface parameters and 10 pressure level parameters, from the
[parameter database](https://apps.ecmwf.int/codes/grib/param-db/).

**Surface** — temperature (`2t`, `2d`, `skt`), wind (`10u`, `10v`, `100u`,
`100v`, `10fg`), pressure (`msl`, `sp`), precipitation (`tp`, `cp`, `sf`,
`tprate`, `ptype`, `sd`, `rsn`, `asn`), cloud (`tcc`, `hcc`, `mcc`, `lcc`),
radiation (`ssr`, `ssrd`, `str`, `strd`, `ttr`), the water and ice budgets
(`tcw`, `tcwv`, `tciw`, `tclw`, `tcrw`, `ro`), the sea (`zos`, `sithick`,
`sve`, `svn`), stability (`mucape`), the surface (`lsm`, `z`, `sdor`,
`slor`) and the stress (`ewss`, `nsss`).

**Pressure level** — `t`, `u`, `v`, `q`, `r`, `z`, `gh`, `w`, `vo`, `d` on
fourteen levels from 1000 to 10 hPa. The open data publishes them on
1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50 and 10 hPa;
this project fetches four of them, which is configurable.

**Soil** parameters (`vsw`, `sot`) are in the 0.25° tier but not in the
0.1° one.

### The units, and the trap in them

The values are stored in SI, and the unit is not always the same for the
same parameter:

| Parameter | IFS | AIFS |
| --- | --- | --- |
| Total precipitation | metres (`m`) | kilograms per square metre (`kg m-2`, which is millimetres) |
| Cloud cover | fraction (`0 - 1`) | percent (`%`) |

Converting as if they were the same puts AIFS at a thousand times the rain
of IFS and a hundred times the cloud. The conversion in `parameters.py` looks
at the unit the value was stored with, so the two are always right.

## The file layout on the portal

```
https://data.ecmwf.int/forecasts/{yyyymmdd}/{HH}z/{model}/{resol}/{stream}/
    {yyyymmddHH}0000-{step}h-{stream}-{type}{-levfile}.{grib2|index}
```

For example the 12 UTC run of the IFS at 0.1°:

```
.../20261020/12z/ifs/0p1/oper/20261020120000-24h-oper-fc-sfc.grib2
```

At 0.1° the surface and the pressure level fields are in **separate files**,
which is why the name ends in `-sfc` or `-pl`. At 0.25° they are together.
The `step` is the forecast hour, and the steps of a run are 0 to 144 in
three hour steps and then 150 to 360 in six hour steps.

Next to every file is an `index` file, which lists the messages inside it
with their byte offsets. That is what makes the downloads small, see
[the data retriever](retrieval.md).

The naming is described in
[File naming and formats](https://confluence.ecmwf.int/spaces/DAC/pages/738041084/ECMWF+open+data+file+naming+and+formats).

## How much of it there is

| | |
| --- | --- |
| One step, all 48 surface parameters, 0.1° | 84 MB |
| One step, 10 pressure parameters on 4 levels, 0.1° | 118 MB |
| One step, everything, 0.1° | 202 MB |
| One run, 26 steps, everything, 0.1° | 4.6 GB |
| One run, everything, all three models | 6.1 GB |

Every parameter is a full global field, so the cost is in the parameters and
the levels, not in the number of places. Adding places is nearly free.
