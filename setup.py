from setuptools import setup

setup(name='cbpi4-4-20ma-analog-sensor',
      version='0.0.1',
      description='CraftBeerPi4 Plugin for ADS1256 based analog sensor',
      author='littlem',
      author_email='mjiao1purdue@qq.com',
      url='',
      include_package_data=True,
      package_data={
        # If any package contains *.txt or *.rst files, include them:
      '': ['*.txt', '*.rst', '*.yaml'],
      'cbpi4_analog_sensor': ['*','*.txt', '*.rst', '*.yaml']},
      packages=['cbpi4-4-20ma-analog-sensor'],
	    install_requires=[
        'PiPyADC']

     )
