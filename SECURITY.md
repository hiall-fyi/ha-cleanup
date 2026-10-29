# Security policy

## Reporting a vulnerability

Please report it privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Don't open a public issue for it.

Include the version (shown in the menu header), how you run the tool, and the smallest steps that show the problem. I'll reply on the report itself.

## What's worth reporting

HA Cleanup runs on your Home Assistant machine with enough access to edit the registry files in `.storage`, modify the recorder database, and stop and start Home Assistant. Reports that matter most are the ones where it could:

- write or delete something it wasn't asked to
- leave a file with wider permissions than it had before
- run a command other than the fixed Home Assistant stop and start commands
- be steered by a crafted registry, backup or database file

It uses only the Python standard library, so there are no third-party packages to patch.

## Supported versions

Only the latest release gets fixes. If you're on an older one, update first and check whether the problem is still there.
