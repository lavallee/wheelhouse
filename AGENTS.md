# Working in this repo

- `template/` is both the reference admin and the source of every shared part.
  Change a shared part there, run `./ci.sh`, then rebuild the registry.
- A part earns a place in `registry.json` when two admins need it. Take it from
  the better existing copy. Do not name the admin it came from: this repository
  is public, and `./ci.sh` refuses private names, hostnames and local paths.
- Screens in the template use invented sample data. Keep its volume
  production-shaped (over a hundred rows) so layouts are judged honestly.
- Check any UI change in a browser at 1440 and 390 wide.
- The design lead owns what belongs here and reviews each adoption, in a browser.
