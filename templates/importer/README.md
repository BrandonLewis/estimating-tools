# Importer template

Copy this directory to add an importer for your own legacy estimate format:

    cp -r templates/importer my-importer

Edit `importer.py`: rename `ExampleImporter`, make `detect()` recognize your file,
and `parse()` build a `CanonicalEstimate` (project + schedules + line items with
`item_number`, optional `item_code`, quantity, unit, unit_price). Register it:

    from estimating_tools.importers import register
    register(MyImporter())

Then `est-import <file>` (or `import_file(path)`) will dispatch to it. The
canonical output is plain, open JSON — your data, in a format you own. Rates and
persistence are out of scope; import produces data only.
