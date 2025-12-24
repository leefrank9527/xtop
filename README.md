# xtop
A terminal monitor fos FPS, System Usage and Docker Stats

Make sure to have the latest version of PyPA’s build and Twine installed:
```angular2html
python3 -m pip install --upgrade build twine
```

Now run this command from the same directory where pyproject.toml is located:
```angular2html
python3 -m build
```

Run Twine to upload all of the archives under dist:
```angular2html
python3 -m twine upload --repository testpypi dist/*
```

You can use pip to install your package and verify that it works. Create a virtual environment and install your package from TestPyPI:
```angular2html
python3 -m pip install --force-reinstall --index-url https://test.pypi.org/simple/ --no-deps xtop-cli
<!--python3 -m pip install &#45;&#45;force-reinstall &#45;&#45;index-url https://test.pypi.org/simple/ xtop-cli-->
```

Once tested, run Twine to upload all of the archives under dist. Now that you’re uploading the package in production, you don’t need to specify --repository; the package will upload to https://pypi.org/ by default.:
```angular2html
python3 -m twine upload dist/*
```
