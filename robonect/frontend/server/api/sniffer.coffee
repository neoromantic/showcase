########################################################################################################################
#
#   Методы, связанные с анализатором трафика
#
########################################################################################################################

Future = Meteor.npmRequire 'fibers/future'
Spawn = Meteor.npmRequire('child_process').spawn
Exec = Meteor.npmRequire('child_process').exec
Splitter = Meteor.npmRequire 'stream-splitter'
FS = Meteor.npmRequire 'fs'

activeSniffer = false

Meteor.methods

  # Запускает tshark, слушает его поток вывода, перенаправляет этот поток на клиента через Meteor Streams.
  snifferStart: (filter, duration = 30) ->
    if not @userId
      throw new Meteor.Error(403)

    if not activeSniffer

      params = [
        '-n', '19', 'tshark',
        '-a', 'duration:' + duration,
        '-a', 'filesize:5000',
        '-n',
        '-w', '/tmp/' + moment().unix() + '_dump.pcap'
      ]
      unless Meteor.settings.public.sniffer_any_interface
        params.push '-i', 'eth0'

      if filter
        params.push '-f'
        params.push filter

      activeSniffer = Spawn 'nice', params

      activeSniffer.stdout.on "data", (data) ->
        outputStream.emit 'message', data.toString()

      activeSniffer.stderr.on "data", (data) ->
        outputStream.emit 'error', data.toString()

      activeSniffer.on 'close', ->
        activeSniffer = false
        snifferStream.emit 'completed', true

      activeSniffer.pid

    else
      throw new Meteor.Error(500, "Сниффер уже запущен, их нельзя два")

  # Убивает tshark
  snifferStop: ->
    if not @userId
      throw new Meteor.Error(403)
    if activeSniffer
      activeSniffer.kill 'SIGKILL'

  snifferDumps: ->
    if not @userId
      throw new Meteor.Error(403)

    files = _.filter FS.readdirSync('/tmp'), (filename) -> filename.indexOf('dump.pcap') != -1 and filename.indexOf('packet') == -1

    files = _.map files, (filename) ->
      stats = FS.statSync '/tmp/' + filename

      name: filename
      modified: stats.mtime

    files = _.sortBy(files, 'modified').reverse().slice(0,3)

    futures = _.map files, (filestat) ->
      fut = new Future()
      onComplete = fut.resolver()

      output = Exec 'tshark -r /tmp/' + filestat.name + ' -qz io,stat,0', (err, stdout, stderr) ->
        filestat.output = stdout

        lines = stdout.split('\n')
        tokens = lines[lines.length - 3]?.split('|')
        [frames, bytes] = [tokens?[2], tokens?[3]]

        filestat.bytes = bytes or 0
        filestat.packets = frames or 0
        filestat.interval = stdout.match(/([0-9\.]+) secs/m)?[1]

        onComplete(false, filestat)

      fut

    Future.wait futures

    _.invoke futures, 'get'

  # Возвращает содержимое дампа (без внутренностей пакетов)
  snifferData: (filename, page) ->
    if not @userId
      throw new Meteor.Error(403)
    if not FS.existsSync '/tmp/' + filename
      return []

    if not page
      page = 1

    params = ['-n','-r', '/tmp/' + filename]

    fut = new Future()
    result = []

    command = Spawn 'tshark', params
    splitter = command.stdout.pipe(Splitter("\n"))
    errors = command.stderr.pipe(Splitter("\n"))
    errors.on "token", (data) -> outputStream.emit 'error', data.toString()
    splitter.on "token", (data) ->
      result.push data.toString()

    command.on 'close', ->
      fut['return'](result.slice((page-1)*100,page*100))

    fut.wait()

  # Возвращает отдельный пакет, для этого вызывает программу 'editpap' и выделяет пакет из большого файла в отдельный
  snifferGetPacket: (filename, packet_index) ->
    if not @userId
      throw new Meteor.Error(403)
    Exec 'rm /tmp/packet_*.pcap'

    params = ['-r', '/tmp/' + filename, '/tmp/packet_' + packet_index + '_' + filename, packet_index]

    fut = new Future()

    command = Spawn 'editcap', params

    command.on "close", ->

      result = []

      tshark = Spawn 'tshark', ['-PVn','-r','/tmp/packet_' + packet_index + '_' + filename]

      splitter = tshark.stdout.pipe(Splitter("\n"))
      splitter.on "token", (data) ->
        result.push data.toString()

      tshark.on 'close', ->
        fut['return'](result)

    fut.wait()
