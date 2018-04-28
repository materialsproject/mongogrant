from setuptools import setup

setup(
    name='mongogrant',
    version='0.1.0',
    packages=['mongogrant'],
    url='https://github.com/materialsproject/mongogrant/',
    license='modified BSD',
    author='MP Team',
    author_email='feedback@materialsproject.org',
    description='Generate and grant credentials for MongoDB databases',
    install_requires=["pymongo", "Flask", "requests"],
)
