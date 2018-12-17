# from distutils.core import setup
from setuptools import setup, find_packages

setup(
    name='py-eyepi',
    version='0.2.5-5',
    python_requires='>=3.2',
    packages=['libeyepi', "eyepiscripts"],
    url='https://borevitzlab.github.io/py-eyepi/',
    license='GPLv3',
    author='Gareth Dunstone, Borevitz Lab, Australian Plant Phenomics Facility, TimeScience',
    author_email='appf@anu.edu.au',
    description='a tool to capture images from dslrs and raspberry pi cameras',
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Science/Research",
        "Operating System :: Unix",
        "Programming Language :: Python :: 3 :: Only"
    ],
    keywords=['timelapse', 'imaging'],
    entry_points={
        'console_scripts': [
            'py-eyepi = eyepiscripts.pyeyepi:main'
        ]
    },
    install_requires=[
        "Pillow",
        "numpy",
        "python-dateutil>=2.6.1",
        "toml>=0.9.1",
        "picamera>=1.13",
        "pyudev>=0.21.0",
        "pytelegraf[http]>=0.3.0"
    ]
)
