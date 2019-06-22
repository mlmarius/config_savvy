# Always prefer setuptools over distutils
# To use a consistent encoding
from codecs import open
from os import path

from setuptools import setup, find_packages

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='config_savvy',  # Required
    version='0.0.1',  # Required
    description='Configuration utilities',  # Required
    long_description=long_description,  # Optional
    package_dir={'': 'src'},
    packages=find_packages('src'),
    install_requires=[],
    setup_requires=['pytest-runner'],
    tests_require=['pytest']
)
