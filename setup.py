from setuptools import setup, find_packages

with open("README.md") as readme_file:
    README = readme_file.read()

with open("HISTORY.md") as history_file:
    HISTORY = history_file.read()

setup_args = dict(
    name="django-custom-cache-page",
    version="0.4",
    description="A customizable implementation of Django's cache_page decorator.",
    long_description_content_type="text/markdown",
    long_description=README + "\n\n" + HISTORY,
    license="MIT",
    packages=find_packages(),
    author="Mohamad Bahamdain",
    author_email="i@mhmd.dev",
    keywords=["Django", "Django Cache", "cache_page"],
    url="https://github.com/zidsa/django-custom-cache-page",
    download_url="https://pypi.org/project/django-custom-cache-page/",
    python_requires=">=3.9",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Framework :: Django",
        "Framework :: Django :: 4.2",
        "Framework :: Django :: 5.0",
        "Framework :: Django :: 5.1",
        "Framework :: Django :: 6.0",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: MIT License",
    ],
)

install_requires = [
    "django>=4.2",
]

if __name__ == "__main__":
    setup(
        **setup_args,
        install_requires=install_requires,
        extras_require={
            "dev": [
                "pytest",
                "pytest-cov",
                "pytest-django",
            ]
        },
    )
