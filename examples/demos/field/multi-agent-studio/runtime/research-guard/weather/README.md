# Weather sources

Forecasts are derived from [MET Norway Locationforecast](https://api.met.no/weatherapi/locationforecast/2.0/documentation) under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The client converts timestamps to city time, selects forecast periods and summarizes available temperature samples. Cite the source and license in weather replies and exported pages.

City coordinates and time zones are adapted from the [GeoNames cities15000 extract](https://download.geonames.org/export/dump/) under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The table includes names and alternate spellings, population, country and region names/codes, coordinates truncated to four decimal places and the time zone. A city with at least 100,000 residents and ten times the population of its next most populous namesake is selected by default. An explicit country or region always narrows the search first. Rebuild with `python3 scripts/build_weather_cities.py DIRECTORY` using `cities15000.zip`, `countryInfo.txt` and `admin1CodesASCII.txt` from the same GeoNames dump. Lookup is offline. Small towns may be absent.

The client identifies the application and caches forecasts according to the [MET Weather API terms](https://api.met.no/doc/TermsOfService).

OpenShell agents run the same forecast helper inside their own workspace. Only `api.met.no` needs network permission.
