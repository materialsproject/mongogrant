import os

from setuptools import setup, find_packages

module_dir = os.path.dirname(os.path.abspath(__file__))

setup(
    name='mongogrant',
    version="0.3.2",
    packages=find_packages(),
    include_package_data=True,
    url='https://github.com/materialsproject/mongogrant/',
    license='modified BSD',
    author='MP Team',
    author_email='feedback@materialsproject.org',
    description='Generate and grant credentials for MongoDB databases',
    long_description=open(os.path.join(module_dir, 'README.md')).read(),
    long_description_content_type="text/markdown",
    install_requires=[
        "Click",
        "pymongo>=3.8",
        "Flask>=1.0",
        "requests",
    ],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Intended Audience :: System Administrators',
        'Intended Audience :: Developers',
        'Topic :: Database',
        'Topic :: Database :: Database Engines/Servers',
        'Topic :: Database :: Front-Ends',
        'Topic :: System :: Systems Administration',
    ],
    keywords='mongodb pymongo authentication authorization',
    python_requires='>=3',
    entry_points='''
        [console_scripts]
        mgrant=mongogrant.scripts.mgrant:cli
    ''',
)