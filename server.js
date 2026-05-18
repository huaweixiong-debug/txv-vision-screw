'use strict';
var express = require('express');
var path = require('path');
var v = require('express-validator');
var m = require('./modbusService');

var app = express();
var PORT = 3000;

app.use('/api', express.json({limit:'10kb'}));
app.use(express.static(path.join(__dirname,'public')));

function ok(res, data){ res.json(Object.assign({success:true},data)); }
function fail(res, msg){ res.json({success:false, message:msg}); }
function check(req,res,next){ var e=v.validationResult(req); if(!e.isEmpty()){ return fail(res,e.array().map(function(x){return x.msg;}).join('; ')); } next(); }

app.post('/api/connect',[
  v.body('ip').trim().isIP().withMessage('invalid ip'),
  v.body('port').optional().isInt({min:1,max:65535}).withMessage('invalid port'),
],check, function(req,res){
  m.modbusService.connect(req.body.ip, req.body.port||502).then(function(){
    ok(res,{message:'connect ok'});
  }).catch(function(e){
    fail(res,e.message);
  });
});

app.get('/api/status', function(req,res){
  if(!m.modbusService.connected){
    return res.json({connected:false,enabled:false,running:false,currentJob:0,currentStep:0,resultCode:0,errorCode:0});
  }
  Promise.all([
    m.modbusService.readInputRegister(m.REGISTERS.INPUT.DEVICE_STATUS).catch(function(){return 0;}),
    m.modbusService.readInputRegister(m.REGISTERS.INPUT.RESULT_CODE).catch(function(){return 0;}),
    m.modbusService.readInputRegister(m.REGISTERS.INPUT.ERROR_CODE).catch(function(){return 0;}),
    m.modbusService.readInputRegister(m.REGISTERS.INPUT.CURRENT_JOB).catch(function(){return 0;}),
    m.modbusService.readInputRegister(m.REGISTERS.INPUT.CURRENT_STEP).catch(function(){return 0;}),
  ]).then(function(r){
    var sw=r[0], rc=r[1], ec=r[2], job=r[3], step=r[4];
    res.json({
      connected:true, enabled:!!(sw&1), running:!!(sw&2),
      currentJob:job, currentStep:step, resultCode:rc, errorCode:ec
    });
  }).catch(function(e){
    res.json({connected:false,enabled:false,running:false,currentJob:0,currentStep:0,resultCode:0,errorCode:0});
  });
});

app.post('/api/start', function(req,res){
  m.modbusService.writeRegister(m.REGISTERS.HOLDING.CONTROL_WORD,1).then(function(){
    var start=Date.now(), timeout=30000;
    function poll(){
      if(Date.now()-start>timeout) return fail(res,'timeout');
      Promise.all([
        m.modbusService.readInputRegister(m.REGISTERS.INPUT.RESULT_CODE),
        m.modbusService.readInputRegister(m.REGISTERS.INPUT.ERROR_CODE),
      ]).then(function(r){
        var rc=r[0], ec=r[1];
        if(rc>=4){
          var ok2=rc===4||rc===5||rc===6;
          return res.json({success:ok2, message:ok2?'OK':'NG', resultCode:rc, errorCode:ec});
        }
        setTimeout(poll,500);
      }).catch(function(){ setTimeout(poll,500); });
    }
    poll();
  }).catch(function(e){ fail(res,e.message); });
});

app.post('/api/setparams',[
  v.body('targetNm').isFloat({min:0,max:9999}).withMessage('bad targetNm'),
  v.body('highNm').isFloat({min:0,max:9999}).withMessage('bad highNm'),
  v.body('lowNm').isFloat({min:0,max:9999}).withMessage('bad lowNm'),
  v.body('speedRpm').isInt({min:0,max:99999}).withMessage('bad speedRpm'),
  v.body('thresholdNm').isFloat({min:0,max:9999}).withMessage('bad thresholdNm'),
],check, function(req,res){
  var b=req.body;
  Promise.resolve()
    .then(function(){ return m.modbusService.writeFloat32(m.REGISTERS.HOLDING.TARGET_TORQUE, b.targetNm); })
    .then(function(){ return m.modbusService.writeFloat32(m.REGISTERS.HOLDING.HIGH_TORQUE, b.highNm); })
    .then(function(){ return m.modbusService.writeFloat32(m.REGISTERS.HOLDING.LOW_TORQUE, b.lowNm); })
    .then(function(){ return m.modbusService.writeRegister(m.REGISTERS.HOLDING.SPEED_RPM, b.speedRpm); })
    .then(function(){ return m.modbusService.writeFloat32(m.REGISTERS.HOLDING.THRESHOLD_TORQUE, b.thresholdNm); })
    .then(function(){ return m.modbusService.writeRegister(m.REGISTERS.HOLDING.CONTROL_WORD, 4); })
    .then(function(){ return new Promise(function(r){ setTimeout(r,500); }); })
    .then(function(){ return m.modbusService.readInputRegister(m.REGISTERS.INPUT.CURRENT_JOB); })
    .then(function(job){ ok(res,{message:'params set, JOB '+job}); })
    .catch(function(e){ fail(res,e.message); });
});

app.post('/api/reset', function(req,res){
  m.modbusService.writeRegister(m.REGISTERS.HOLDING.CONTROL_WORD,2).then(function(){
    return new Promise(function(r){ setTimeout(r,500); });
  }).then(function(){
    return m.modbusService.readInputRegister(m.REGISTERS.INPUT.ERROR_CODE);
  }).then(function(ec){
    if(ec===0) ok(res,{message:'reset ok'});
    else fail(res,'reset errorCode='+ec);
  }).catch(function(e){ fail(res,e.message); });
});

app.post('/api/stop', function(req,res){
  m.modbusService.writeRegister(m.REGISTERS.HOLDING.CONTROL_WORD,3).then(function(){
    ok(res,{message:'stop sent'});
  }).catch(function(e){ fail(res,e.message); });
});

app.use('/api/*', function(req,res){ fail(res,'unknown: '+req.method+' '+req.path); });

app.listen(PORT, function(){
  console.log('Server ready: http://localhost:'+PORT+'/api');
});

module.exports = app;
