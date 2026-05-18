var m = require('./modbusService');
async function test(ip, label) {
    try {
        await m.modbusService.connect(ip, 502);
        var r = await Promise.all([
            m.modbusService.readInputRegister(0),
            m.modbusService.readInputRegister(1),
            m.modbusService.readInputRegister(2),
            m.modbusService.readInputRegister(3),
            m.modbusService.readInputRegister(4),
        ]);
        console.log(label + ' OK: ' + JSON.stringify({sw:r[0], rc:r[1], ec:r[2], job:r[3], step:r[4]}));
    } catch(e) {
        console.log(label + ' FAIL: ' + e.message);
    }
}
test('192.168.0.99', 'GUN').then(function() {
    return test('192.168.0.111', 'CAMERA');
}).then(function() {
    process.exit(0);
});