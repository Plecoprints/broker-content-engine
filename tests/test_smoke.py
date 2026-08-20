def test_package_imports_and_has_version():
    import bce
    assert isinstance(bce.__version__, str)
    assert bce.__version__ == "0.1.0"
