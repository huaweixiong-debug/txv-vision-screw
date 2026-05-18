'use strict';

const ModbusRTU = require('modbus-serial');

// Modbus 地址映射（根据 MODBUS 协议文档）
const REGISTERS = {
  // 保持寄存器 (4xxxx)
  HOLDING: {
    CONTROL_WORD:     0,    // 控制字 (0=停止, 1=启动, 2=复位, 3=紧停)
    TARGET_TORQUE:    10,   // 目标扭矩 Float32 (2 regs)
    HIGH_TORQUE:      12,   // 上限扭矩 Float32 (2 regs)
    LOW_TORQUE:       14,   // 下限扭矩 Float32 (2 regs)
    SPEED_RPM:        16,   // 转速 UINT16
    THRESHOLD_TORQUE: 18,   // 阈值扭矩 Float32 (2 regs)
  },
  // 输入寄存器 (3xxxx) - 只读状态
  INPUT: {
    DEVICE_STATUS:    0,    // 设备状态字
    RESULT_CODE:      1,    // 结果码
    ERROR_CODE:       2,    // 故障码
    CURRENT_JOB:      3,    // 当前工作号
    CURRENT_STEP:     4,    // 当前步骤
    TORQUE_ACTUAL:    10,   // 实际扭矩 Float32 (2 regs)
  }
};

// 结果码映射 (来自协议文档)
const RESULT_MAP = {
  0: 'NONE',    1: 'READY',   2: 'RUNNING',
  4: 'OK',      5: 'OK-SEQ',  6: 'OK-JOB',
  7: 'NG',      8: 'NS',      9: 'TIMEOUT'
};

class ModbusError extends Error {
  constructor(message, code) {
    super(message);
    this.name = 'ModbusError';
    this.code = code || 'MODBUS_ERROR';
  }
}

class ModbusService {
  constructor() {
    this.client = null;
    this.connected = false;
    this.connecting = false;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 3;
    this.baseDelayMs = 1000;
  }

  async connect(ip, port = 502) {
    if (this.connected) {
      await this.disconnect();
    }

    this.connecting = true;
    this.client = new ModbusRTU();
    this.client.setTimeout(5000);

    try {
      console.log(`[Modbus] 连接设备 ${ip}:${port} ...`);
      await this.client.connectTCP(ip, { port });
      this.connected = true;
      this.reconnectAttempts = 0;
      console.log('[Modbus] 连接成功');
    } catch (err) {
      this.connected = false;
      console.error(`[Modbus] 连接失败: ${err.message}`);
      throw new ModbusError(`连接失败: ${err.message}`, 'CONNECT_FAILED');
    } finally {
      this.connecting = false;
    }
  }

  async disconnect() {
    if (!this.client) return;
    try {
      this.client.close();
      console.log('[Modbus] 已断开连接');
    } catch (err) {
      // 忽略断连错误
    }
    this.client = null;
    this.connected = false;
  }

  async _reconnect() {
    if (this.connecting) return false; if (this.reconnectAttempts >= this.maxReconnectAttempts) return false;
    if (false) {
      console.error('[Modbus] 已达最大重连次数');
      return false;
    }

    this.reconnectAttempts++;
    const delay = this.baseDelayMs * Math.pow(2, this.reconnectAttempts - 1);
    console.log(`[Modbus] 第${this.reconnectAttempts}次重连 (${delay}ms后)...`);

    await new Promise(resolve => setTimeout(resolve, delay));

    try {
      if (this.client) {
        await this.client.connectTCP(
          this.client.host||this.client._host,
          { port: this.client.port||this.client._port||502 }
        );
        this.connected = true;
        this.reconnectAttempts = 0;
        console.log('[Modbus] 重连成功');
        return true;
      }
    } catch (err) {
      console.error(`[Modbus] 重连失败: ${err.message}`);
    }
    return false;
  }

  async _ensureConnected() {
    if (!this.client || !this.connected) {
      if (!await this._reconnect()) {
        throw new ModbusError('设备未连接', 'NOT_CONNECTED');
      }
    }
  }

  async readHoldingRegister(addr) {
    await this._ensureConnected();
    try {
      const { data } = await this.client.readHoldingRegisters(addr, 1);
      return data[0];
    } catch (err) {
      console.error(`[Modbus] 读保持寄存器[${addr}]失败: ${err.message}`);
      this.connected = false;
      throw new ModbusError(`读寄存器失败: ${err.message}`, 'READ_FAILED');
    }
  }

  async readInputRegister(addr) {
    await this._ensureConnected();
    try {
      const { data } = await this.client.readInputRegisters(addr, 1);
      return data[0];
    } catch (err) {
      console.error(`[Modbus] 读输入寄存器[${addr}]失败: ${err.message}`);
      this.connected = false;
      throw new ModbusError(`读寄存器失败: ${err.message}`, 'READ_FAILED');
    }
  }

  async writeCoil(addr, value) {
    await this._ensureConnected();
    try {
      await this.client.writeCoil(addr, !!value);
      console.log(`[Modbus] 写线圈[${addr}]=${!!value}`);
    } catch (err) {
      console.error(`[Modbus] 写线圈[${addr}]失败: ${err.message}`);
      this.connected = false;
      throw new ModbusError(`写线圈失败: ${err.message}`, 'WRITE_FAILED');
    }
  }

  async writeRegister(addr, value) {
    await this._ensureConnected();
    try {
      await this.client.writeRegister(addr, value);
      console.log(`[Modbus] 写保持寄存器[${addr}]=${value}`);
    } catch (err) {
      console.error(`[Modbus] 写寄存器[${addr}]失败: ${err.message}`);
      this.connected = false;
      throw new ModbusError(`写寄存器失败: ${err.message}`, 'WRITE_FAILED');
    }
  }

  // 大端序 (Big-Endian ABCD): 高16位在前
  async readFloat32(startAddr) {
    await this._ensureConnected();
    try {
      const { data } = await this.client.readHoldingRegisters(startAddr, 2);
      // data[0]=高16位, data[1]=低16位 → Big-Endian ABCD
      const buf = Buffer.allocUnsafe(4);
      buf.writeUInt16BE(data[0], 0);
      buf.writeUInt16BE(data[1], 2);
      return buf.readFloatBE(0);
    } catch (err) {
      console.error(`[Modbus] 读Float32[${startAddr}]失败: ${err.message}`);
      this.connected = false;
      throw new ModbusError(`读浮点数失败: ${err.message}`, 'READ_FAILED');
    }
  }

  // 大端序 Float32 写入 (2 个寄存器)
  async writeFloat32(startAddr, value) {
    await this._ensureConnected();
    try {
      const buf = Buffer.allocUnsafe(4);
      buf.writeFloatBE(value, 0);
      const high = buf.readUInt16BE(0);
      const low  = buf.readUInt16BE(2);
      await this.client.writeRegisters(startAddr, [high, low]);
      console.log(`[Modbus] 写Float32[${startAddr}]=${value}`);
    } catch (err) {
      console.error(`[Modbus] 写Float32[${startAddr}]失败: ${err.message}`);
      this.connected = false;
      throw new ModbusError(`写浮点数失败: ${err.message}`, 'WRITE_FAILED');
    }
  }
}

// 单例
const modbusService = new ModbusService();

module.exports = { modbusService, ModbusError, REGISTERS, RESULT_MAP };
