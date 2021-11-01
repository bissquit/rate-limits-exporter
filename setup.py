from setuptools import find_packages, setup

setup(
    name='rate_limits_exporter',
    # extras_require={'tests': ['pytest']},
    packages=find_packages(where="src"),
    # package_dir={"": "src"},
    install_requires=['pytest', 'pytest-mock']
)

