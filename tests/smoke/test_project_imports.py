def test_src_package_imports():
    import src

    assert src.__version__ == "0.1.0"
