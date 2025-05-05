from setuptools import setup, find_packages

with open("README.md", "r") as f:
    long_description = f.read()

setup(
    name='genai-protocol-lite',
    version='1.0.0',
    description="GenAI Python project for direct agents connection either locally via websockets or remote via Azure Web PubSub",
    long_description=open('README.md', encoding='utf-8').read(),
    long_description_content_type='text/markdown',
    author="Yaroslav Oliinyk, Yaroslav Motalov, Ivan Kuzlo",
    author_email="yaroslav.oliinyk@chisw.com, yaroslav.motalov@chisw.com, ivan.kuzlo@chisw.com",
    url="https://github.com/genai-works-org/genai-protocol-lite",
    readme="README.md",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    license="Apache License 2.0",
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    install_requires=[
        "wcwidth==0.2.13",
        "websockets~=15.0",
        "colorlog==6.9.0",
        "azure-messaging-webpubsubservice==1.2.1",
    ],
    extras_require={
        "dev": ["twine>=6.1.0"],
    },
    python_requires='>=3.9',
)
