#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
import struct
import time
import serial


class DeviceBoardEmulator:
    """Эмулятор платы буйкового уровнемера с симуляцией физики процессов"""

    def __init__(self, port: str):
        self.ser = serial.Serial(
            port=port,
            baudrate=1200,
            parity=serial.PARITY_ODD,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
            timeout=0.5,
        )
        self.serial_number = 20260521
        self.fw_major = 1
        self.fw_minor = 6
        self.device_address = 0

        # Калибровочные и конструктивные параметры
        self.density_setting = 1000.0
        self.base_density = 1000.0
        self.buoy_mass = 500.0
        self.buoy_volume = 120.0
        self.max_range_mm = 1000.0
        self.temperature = 20.0
        self.tick_counter = 0

    def _calculate_lrc(self, data: bytes) -> int:
        lrc = 0
        for byte in data:
            lrc ^= byte
        return lrc

    def update_physics(self):
        """Расчет изменения уровня и температуры с термокомпенсацией плотности среды"""
        self.tick_counter += 1

        # Симуляция изменения уровня (периодический волновой процесс)
        wave_level = math.sin(self.tick_counter * 0.05)
        current_level_ratio = 0.5 + (wave_level * 0.4)

        # Симуляция изменения температуры датчика (медленный тепловой дрейф от +15°C до +55°C)
        wave_temp = math.cos(self.tick_counter * 0.02)
        self.temperature = float(35.0 + (wave_temp * 20.0))

        # Расчет изменения плотности среды по температурному коэффициенту расширения
        gamma = 0.0008
        delta_t = self.temperature - 20.0
        actual_fluid_density = self.density_setting * (1.0 - (gamma * delta_t))

        # Корректировка уровня под выталкивающую силу (изменение осадки буйка)
        corrected_level_ratio = current_level_ratio * (
            self.density_setting / actual_fluid_density
        )
        corrected_level_ratio = max(0.0, min(1.0, corrected_level_ratio))

        # Формирование токовой петли 4-20 мА
        current_loop_mA = 4.0 + (corrected_level_ratio * 16.0)
        if self.density_setting < 100.0:
            current_loop_mA = 3.6

        return corrected_level_ratio, current_loop_mA

    def run(self):
        print(f"Эмулятор аппаратной платы запущен на порту {self.ser.port}...\n")
        while True:
            if self.ser.in_waiting > 0:
                rx_data = self.ser.read(64)
                try:
                    start_idx = rx_data.index(0x02)
                except ValueError:
                    continue

                pdu_request = rx_data[start_idx:]
                if len(pdu_request) < 4:
                    continue

                cmd_num = pdu_request[2]
                data_len = pdu_request[3]
                payload = pdu_request[4 : 4 + data_len]

                level, current = self.update_physics()
                reply_payload = bytearray([0x00, 0x00])

                if cmd_num == 0:
                    reply_payload.append(self.device_address)
                    reply_payload.append(0x01)
                    reply_payload.append(0x04)

                elif cmd_num == 2:
                    reply_payload.extend(struct.pack(">f", float(current)))

                elif cmd_num == 3:
                    reply_payload.extend(b"\x00\x00\x00")
                    reply_payload.extend(struct.pack(">f", float(level)))
                    reply_payload.append(0x00)
                    reply_payload.extend(struct.pack(">f", float(self.temperature)))
                    print(
                        f" -> HART Cmd 3: Уровень {level:.3f} м, Температура: {self.temperature:.1f} °C"
                    )

                elif cmd_num == 12:
                    if len(payload) >= 4:
                        self.max_range_mm = float(struct.unpack(">f", payload)[0])
                    reply_payload.extend(
                        struct.pack(">f", float(self.max_range_mm))
                    )

                elif cmd_num == 13:
                    if len(payload) >= 4:
                        self.density_setting = float(struct.unpack(">f", payload)[0])
                    reply_payload.extend(
                        struct.pack(">f", float(self.density_setting))
                    )
                    print(
                        f" -> HART Cmd 13: Плотность обновлена на {self.density_setting} кг/м³"
                    )

                else:
                    reply_payload.append(0x1F)

                # Сборка и отправка кадра ответа HART-Slave платы
                payload_bytes = bytes(reply_payload)
                pdu_body = struct.pack(
                    f"BBB{len(payload_bytes)}s", 0x06, 0x80, cmd_num, payload_bytes
                )
                lrc = self._calculate_lrc(pdu_body)
                full_reply = b"\xFF" * 5 + pdu_body + bytes([lrc])

                time.sleep(0.04)
                self.ser.write(full_reply)
                self.ser.flush()
                time.sleep(0.01)


if __name__ == "__main__":
    try:
        emu = DeviceBoardEmulator(port="COM2")
        emu.run()
    except Exception as e:
        print(f"Критическая ошибка выполнения эмулятора: {e}")
        input()
