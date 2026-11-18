# Sample data (synthetic)

`DEMOA.csv` and `DEMOB.csv` are **simulated** daily bars (seeded geometric
Brownian motion, `SyntheticProvider(seed=11)`). They are not market data and
describe no real instrument. They exist so you can try the "My own CSV files"
data source and see the expected file format:

```
date,open,high,low,close,volume
2018-01-01,100.0,100.5,99.4,100.3,1000000.0
```

In the dashboard: sidebar -> Source -> **My own CSV files** -> upload both files.

From Python:

```python
from quantlab.data import CsvProvider
data = CsvProvider("examples/sample_data").fetch(["DEMOA", "DEMOB"])
```
