# Import/location smoke checks complement, but do not replace, RSA mathematical tests.
from importlib import import_module
from pathlib import Path


def test_rsa_package_imports_from_its_own_boundary() -> None:
    package = import_module("breakingpkc.rsa")
    package_path = Path(package.__file__).resolve()

    assert package_path.parent.name == "rsa"
    assert package_path.parent.parent.name == "breakingpkc"
