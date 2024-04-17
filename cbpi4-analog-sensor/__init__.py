
# -*- coding: utf-8 -*-
import os, threading
import time
from aiohttp import web
import logging
from unittest.mock import MagicMock, patch
from subprocess import call
import asyncio
import random
from cbpi.api import *
from cbpi.api.config import ConfigType
from cbpi.api.base import CBPiBase
from pipyadc import ADS1256
from pipyadc.ADS1256_definitions import *
from . import board_config


logger = logging.getLogger(__name__)
cache = {}

CH0 = POS_AIN0 | NEG_AINCOM
CH1 = POS_AIN1 | NEG_AINCOM
CH2 = POS_AIN2 | NEG_AINCOM
CH3 = POS_AIN3 | NEG_AINCOM
CH4 = POS_AIN4 | NEG_AINCOM
CH5 = POS_AIN5 | NEG_AINCOM
CH6 = POS_AIN6 | NEG_AINCOM
CH7 = POS_AIN7 | NEG_AINCOM

# Arbitrary length tuple of input channel pair values to scan sequentially
CH_SEQUENCE = (CH0, CH1, CH2, CH3, CH4, CH5, CH6, CH7)

class ads1256_Config(CBPiExtension):

    def __init__(self,cbpi):
        self.cbpi = cbpi
        self._task = asyncio.create_task(self.init_sensor())

    async def init_sensor(self):

        global SCD30_Active
        SCD30_Active=False
        await asyncio.sleep(0.1)
        self.ads = ADS1256(board_config)
        self.Interval = self.cbpi.config.get("ads_interval", 5)
        retries = 30
        ready = None
        while ready is None and retries:
            try:
                self.ads.drate = DRATE_100
                self.ads.cal_self()
                ready = self.ads.read_sequence(CH_SEQUENCE)
                SCD30_Active=True
            except OSError:
                # The sensor may need a couple of seconds to boot up after power-on
                # and may not be ready to respond, raising I2C errors during this time.
                pass
            await asyncio.sleep(1)
            retries -= 1
        if not retries:
            logging.error("Timed out waiting for SCD30.")
            pass 
        if ready is not None:    
            # self.ads.drate = DRATE_100
            # self.ads.cal_self()
            # self.ads.read_sequence(CH_SEQUENCE)
            await asyncio.sleep(self.Interval)
            SCD30_Active=True
            # logging.info(f"ASC status: {self.scd30.get_auto_self_calibration_active()}")
            # logging.info(f"Measurement interval: {self.scd30.get_measurement_interval()}s")
            # logging.info(f"Temperature offset: {self.scd30.get_temperature_offset()}'C")
            loop = asyncio.get_event_loop()
            try:
                asyncio.ensure_future(self.ReadSensor())
                loop.run_forever()
            finally:
                loop.close()



    async def ReadSensor(self):
        global cache
        self.ads.drate = DRATE_100
        self.ads.cal_self()
        
        while True:
            try:
                measurement = self.ads.read_sequence(CH_SEQUENCE) 
                volts = [i * self.ads.v_per_digit for i in measurement]
                # read data and covert to voltage data
                if volts is not None:
                    ch0,ch1,ch2,ch3,ch4,ch5,ch6,ch7 = volts
                    timestamp = time.time()
                    cache = {'Time': timestamp,
                            'ch0': ch0,
                            'ch1': ch1,
                            'ch2': ch2,
                            'ch3': ch3,
                            'ch4': ch4,
                            'ch5': ch5,
                            'ch6': ch6,
                            'ch7': ch7}
                await asyncio.sleep(self.Interval)
            except Exception as e:
                print('error!!!', self.Interval)
                pass
            await asyncio.sleep(1)



@parameters([
    Property.Select(label="ADSchannel", options=[0,1,2,3,4,5,6,7], description="Enter channel-number of ADS125x"),
    Property.Select("sensorType", options=["Voltage","Pressure","Liquid Level","Volume"], description="Select which type of data to register for this sensor"),
    Property.Select("pressureType", options=["kPa","PSI"]),
    Property.Number("voltLow", configurable=True, default_value=0, description="Pressure Sensor minimum voltage, usually 0"),
    Property.Number("voltHigh", configurable=True, default_value=5, description="Pressure Sensor maximum voltage, usually 3"),
    Property.Number("pressureLow", configurable=True, default_value=0, description="Pressure value at minimum voltage, value in kPa"),
    Property.Number("pressureHigh", configurable=True, default_value=10, description="Pressure value at maximum voltage, value in kPa"),
    Property.Number("sensorHeight", configurable=True, default_value=0, description="Location of Sensor from the bottom of the kettle in meter"),
    Property.Number("kettleDiameter", configurable=True, default_value=0, description="Diameter of kettle in meter"),
    Property.Select(label="Interval", options=[1,5,10,30,60], description="Interval in Seconds")
])
class Analog_Sensor(CBPiSensor):
    
    def __init__(self, cbpi, id, props):
        super(Analog_Sensor, self).__init__(cbpi, id, props)
        
        self.value = 0
        self.value_old = 0
        self.Interval = int(self.props.get("Interval",5))
        self.time_old = 0
        global SCD30_Active
        global cache
        # Variables to be used with calculations
        self.GRAVITY = 9.807
        self.PI = 3.1416
        # Conversion values
        self.kpa_psi = 0.145
        self.bar_psi = 14.5038
        self.inch_mm = 25.4
        self.gallons_cubicinch = 231
        
        self.sensorHeight = float(self.props.get("sensorHeight", 0))
        self.kettleDiameter = float(self.props.get("kettleDiameter", 0))
        self.ADSchannel = int(self.props.get("ADSchannel", 0))
        self.pressureHigh = self.convert_pressure(int(self.props.get("pressureHigh", 10)))
        self.pressureLow = self.convert_pressure(int(self.props.get("pressureLow", 0)))
    
        
        self.calcX = int(self.props.get("voltHigh", 3)) - int(self.props.get("voltLow", 0))
        #logging.info('calcX value: %s' % (calcX))
        self.calcM = (self.pressureHigh - self.pressureLow) / self.calcX
        #logging.info('calcM value: %s' % (calcM))
        self.calcB = 0
        if int(self.props.get("voltLow", 0)) > 0:
            self.calcB = (-1 * int(self.props.get("voltLow", 0))) * self.calcM
     
        self.max_counter = 2
        # counts subsequent rejected values
        self.counter = 0

        self.lastlog=0

    def v_per_digit(self, value):
        return board_config.v_ref * board_config.gain

    def convert_pressure(self, value):
        if self.props.get("pressureType", "kPa") == "PSI":
            return value * self.kpa_psi
        else:
            return value
    
    def convert_bar(self, value):
        if self.props.get("pressureType", "kPa") == "PSI":
            return value / self.bar_psi
        else:
            return value / 100

    async def run(self):
        while self.running is True:
            try:
                # print(cache)
                if (float(cache['Time']) > float(self.time_old)):
                    self.time_old = float(cache['Time'])
                    if self.ADSchannel == 0:
                        self.value = round(float(cache['ch0']),3)
                    elif self.ADSchannel == 1:
                        self.value = round(float(cache['ch1']),3)
                    elif self.ADSchannel == 2:
                        self.value = round(float(cache['ch2']),3)
                    elif self.ADSchannel == 3:
                        self.value = round(float(cache['ch3']),3)
                    elif self.ADSchannel == 4:
                        self.value = round(float(cache['ch4']),3)
                    elif self.ADSchannel == 5:
                        self.value = round(float(cache['ch5']),3)
                    elif self.ADSchannel == 6:
                        self.value = round(float(cache['ch6']),3)
                    elif self.ADSchannel == 7:
                        self.value = round(float(cache['ch7']),3)
                    # self.value in voltage

                    
                  
                    pressureValue = (self.calcM * self.value) + self.calcB    # "%.6f" % ((calcM * voltage) + calcB)
            
                    # liquidLevel = ((self.convert_bar(pressureValue) / self.GRAVITY) * 100000) / self.inch_mm
                    # if liquidLevel > 0.49:
                    #     liquidLevel += self.sensorHeight
                    # not understand the meaning of 0.49

                    liquidLevel = pressureValue / self.GRAVITY 
                    # in unit of meter
                   
                    
                    # Volume is calculated by V = PI (r squared) * height
                    # kettleRadius = self.kettleDiameter / 2
                    # radiusSquared = kettleRadius * kettleRadius
                    volume = self.PI * (self.kettleDiameter / 2)**2 * liquidLevel * 1000
                    # in unit of liter
                    # volume = volumeCI * 1000 # in unit of liter

                    if self.props.get("sensorType", "Liquid Level") == "Voltage":
                        self.value = self.value
                    elif self.props.get("sensorType", "Liquid Level") == "Pressure":
                        self.value = pressureValue
                    elif self.props.get("sensorType", "Liquid Level") == "Liquid Level":
                        self.value = liquidLevel
                    elif self.props.get("sensorType", "Liquid Level") == "Volume":
                        self.value = volume
                    
                    self.push_update(self.value)
                    self.log_data(self.value)

                self.push_update(self.value,False)
            except Exception as e:
                pass
            await asyncio.sleep(1)

      


    
    def get_state(self):
        return dict(value=self.value)

def setup(cbpi):
    cbpi.plugin.register("ADS1256 Config", ads1256_Config)
    cbpi.plugin.register("ADS1256 Sensor", Analog_Sensor)
    pass
