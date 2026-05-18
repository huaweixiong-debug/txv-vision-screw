'use strict';

const ModbusRTU = require('modbus-serial');

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) {
      continue;
    }

    const key = token.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith('--')) {
      args[key] = true;
      continue;
    }

    args[key] = next;
    i += 1;
  }
  return args;
}

function toInt(value, name) {
  if (value === undefined) {
    return undefined;
  }

  const parsed = Number(value);
  if (!Number.isInteger(parsed)) {
    throw new Error(`${name} must be an integer`);
  }

  return parsed;
}

function u32ToWords(value) {
  if (!Number.isInteger(value) || value < 0 || value > 0xffffffff) {
    throw new Error(`u32 out of range: ${value}`);
  }

  return [(value >>> 16) & 0xffff, value & 0xffff];
}

function wordsToU32(high, low) {
  return ((high >>> 0) * 0x10000) + (low >>> 0);
}

async function readU32(client, addr) {
  const { data } = await client.readHoldingRegisters(addr, 2);
  return wordsToU32(data[0], data[1]);
}

async function writeU32(client, addr, value) {
  const words = u32ToWords(value);
  await client.writeRegisters(addr, words);
}

async function readBlock(client, start, length) {
  const { data } = await client.readHoldingRegisters(start, length);
  return data;
}

async function readStatus(client) {
  const current = await readBlock(client, 4305, 3);
  const live = await readBlock(client, 4168, 16);

  return {
    currentJob: current[0],
    currentSeq: current[1],
    currentStep: current[2],
    live4168_4183: live
  };
}

async function readWorkSnapshot(client) {
  const work = await readBlock(client, 1015, 1);
  const seq = await readBlock(client, 1075, 1);
  const block = await readBlock(client, 1135, 32);

  return {
    workNo: work[0],
    seqNo: seq[0],
    step1Enabled: block[0],
    targetType: block[9],
    targetAngle: wordsToU32(block[10], block[11]),
    targetTorque: wordsToU32(block[12], block[13]),
    delayTenthSec: block[14],
    direction: block[15],
    speed: block[16],
    compensateSign: block[17],
    compensateValue: wordsToU32(block[18], block[19]),
    highTorque: wordsToU32(block[20], block[21]),
    lowTorque: wordsToU32(block[22], block[23]),
    angleMode: block[24],
    angleHigh: wordsToU32(block[25], block[26]),
    angleLow: wordsToU32(block[27], block[28])
  };
}

async function applyWorkStep1(client, options) {
  await client.writeRegister(1135, 1);
  await client.writeRegister(1144, options.targetType ?? 2);

  if (options.targetTorque !== undefined) {
    await writeU32(client, 1147, options.targetTorque);
  }
  if (options.targetAngle !== undefined) {
    await writeU32(client, 1145, options.targetAngle);
  }
  if (options.highTorque !== undefined) {
    await writeU32(client, 1155, options.highTorque);
  }
  if (options.lowTorque !== undefined) {
    await writeU32(client, 1157, options.lowTorque);
  }
  if (options.speed !== undefined) {
    await client.writeRegister(1151, options.speed);
  }
  if (options.angleMode !== undefined) {
    await client.writeRegister(1159, options.angleMode);
  }
  if (options.angleHigh !== undefined) {
    await writeU32(client, 1160, options.angleHigh);
  }
  if (options.angleLow !== undefined) {
    await writeU32(client, 1162, options.angleLow);
  }

  await client.writeRegister(463, 221);
  await client.writeRegister(464, 1);
}

function printUsage() {
  console.log('Usage:');
  console.log('  node kilews_probe.js --ip 192.168.0.105 --action inspect');
  console.log('  node kilews_probe.js --ip 192.168.0.105 --action work-step1 --targetTorque 1234 --speed 500');
  console.log('');
  console.log('Torque values are raw integer values using controller unit multiplier.');
  console.log('For N.m mode, 1.234 N.m = 1234.');
}

async function main() {
  const args = parseArgs(process.argv);
  if (args.help || !args.ip || !args.action) {
    printUsage();
    process.exit(args.help ? 0 : 1);
  }

  const client = new ModbusRTU();
  client.setTimeout(5000);

  try {
    await client.connectTCP(args.ip, { port: toInt(args.port, 'port') || 502 });

    const before = await readStatus(client);
    console.log('=== status-before ===');
    console.log(JSON.stringify(before, null, 2));

    if (args.action === 'inspect') {
      console.log('=== modbus-work-step1 ===');
      console.log(JSON.stringify(await readWorkSnapshot(client), null, 2));
      return;
    }

    const options = {
      targetType: toInt(args.targetType, 'targetType'),
      targetTorque: toInt(args.targetTorque, 'targetTorque'),
      targetAngle: toInt(args.targetAngle, 'targetAngle'),
      highTorque: toInt(args.highTorque, 'highTorque'),
      lowTorque: toInt(args.lowTorque, 'lowTorque'),
      speed: toInt(args.speed, 'speed'),
      thresholdType: toInt(args.thresholdType, 'thresholdType'),
      thresholdTorque: toInt(args.thresholdTorque, 'thresholdTorque'),
      thresholdAngle: toInt(args.thresholdAngle, 'thresholdAngle'),
      angleMode: toInt(args.angleMode, 'angleMode'),
      angleHigh: toInt(args.angleHigh, 'angleHigh'),
      angleLow: toInt(args.angleLow, 'angleLow')
    };

    if (args.action === 'work-step1' || args.action === 'advanced-step1') {
      await applyWorkStep1(client, options);
    } else {
      throw new Error(`unknown action: ${args.action}`);
    }

    const after = await readStatus(client);
    console.log('=== status-after ===');
    console.log(JSON.stringify(after, null, 2));
  } finally {
    try {
      client.close();
    } catch (err) {
      // Ignore close errors.
    }
  }
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
