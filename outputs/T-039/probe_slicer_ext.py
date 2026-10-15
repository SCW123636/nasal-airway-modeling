"""T-039 step 2 probe: introspect Slicer's ExtensionManagerModel (headless).

Run:
  & "D:\\项目\\鼻腔建模\\软件\\slicer\\3D Slicer 5.12.4\\Slicer.exe" \
      --no-splash --no-main-window --python-script <this> --exit-when-finished

Prints version, server config, install path, and available EM methods so we can
pick the correct install call for Slicer 5.12.4 (no GUI).
"""
import sys
import slicer

print("=" * 60)
print("SLICER_VERSION", slicer.app.applicationVersion)
print("SLICER_REVISION", slicer.app.repositoryRevision)
print("SLICER_PLATFORM", slicer.app.platform)

em = slicer.app.extensionsManagerModel()
print("-" * 60)
print("SERVER_URL", em.serverUrl)
try:
    print("FRONTEND_URL", em.frontendServerUrl)
except Exception as e:  # noqa
    print("FRONTEND_URL <err>", e)
print("INSTALL_PATH", em.getExtensionsInstallPath())
print("-" * 60)
methods = [m for m in dir(em) if not m.startswith("_")]
print("METHODS", "\n  ".join([""] + methods))
print("=" * 60)

sys.exit(0)
