# windows_evtx fixtures

| | |
|---|---|
| Source product | Windows Security and System event logs (Windows Server 2022 shape) |
| Collector shape | Native `.evtx` files, as copied or exported from `C:\Windows\System32\winevt\Logs` |
| Generator | `scripts/fixtures/starter_pack.py windows_evtx` (seed 45), using `scripts/fixtures/evtx_writer.py` |
| Values | Synthetic CORP domain, invented users and hosts, RFC 1918 and RFC 5737 addresses |

No real event log is in the repo: `evtx_writer.py` writes the EVTX container (file header, 64 KiB chunks, real CRC32 checksums) with BinXML records that use direct elements and inline names, the subset of MS-EVEN6 that needs no templates. Security events are typed the way Windows writes them (UInt16 EventID, FILETIME SystemTime, HexInt64 Keywords); System events carry the `Qualifiers` attribute, which the evtx library renders as `{"#attributes": ..., "#text": n}`.

- `sample.evtx`: the same 60-event mix as the other Windows fixtures, in two chunks
- `sample.log`: the record JSON the reader frames from `sample.evtx`, which is what lands in `raw`
- `pathological.evtx`: `sample.evtx` with 100 bytes of the first record overwritten; the reader skips that record and keeps the rest
- `pathological.log`: JSON lines with hostile shapes (deep nesting, object where an id belongs, impossible time, null event)
