from setuptools import setup, find_packages

with open('README.md') as readme_file:
    README = readme_file.read()

with open('HISTORY.md') as history_file:
    HISTORY = history_file.read()

setup_args = dict(
    name='django-custom-cache-page',
    version='0.3',
    description='A customizable implementation of Django\'s cache_page decorator.',
    long_description_content_type='text/plain',
    long_description=README + '\n\n' + HISTORY,
    license='MIT',
    packages=find_packages(),
    author='Mohamad Bahamdain',
    author_email='i@mhmd.dev',
    keywords=['Django', 'Django Cache', 'cache_page'],
    url='https://github.com/zidsa/django-custom-cache-page',
    download_url='https://pypi.org/project/django-custom-cache-page/',
    classifiers = [
        'Programming Language :: Python :: 3 :: Only',
        'Framework :: Django',
        'Operating System :: OS Independent',
        'License :: OSI Approved :: MIT License',
    ]
)

install_requires = [
    'django>=2.0',
]

if __name__ == '__main__':
    setup(**setup_args,
          install_requires=install_requires,
          extras_require={
              'dev': [
                  'pytest',
                  'pytest-pep8',
                  'pytest-cov'
              ]
          }
    )
