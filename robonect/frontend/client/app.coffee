Meteor.startup ->

	Session.set "translationsReady", false
	config = Configuration.get()

	TAPi18n.setLanguage("en")
		.done(-> Session.set("translationsReady", true))
		.fail((error_message) -> console.log(error_message))

	# Автоматический рефреш страницы, если соединение лежало больше минуты
	lastDisconnect = false

	Tracker.autorun ->
		health = Meteor.status()
		if lastDisconnect and not health.connected
			Session.set "afterLostConnection", true
		if not lastDisconnect and not health.connected
			lastDisconnect = moment()
		if health.connected
			if lastDisconnect
				if (moment() - lastDisconnect) > 60 * 1000
					location.reload true
			lastDisconnect = false

	Session.set "pageTitle", (config.snmp_sysname or "Robonect") + " | " + (config.snmp_syslocation or "") + " | " + config.device_ip

	Tracker.autorun ->
		document.title = (if config.GSM then "(GSM) " else "") + Session.get("pageTitle")

	Meteor.setInterval ->
		token = Meteor._localStorage.getItem 'Meteor.loginToken'
		if token
			Meteor.apply 'extendToken', [token, true], onResultReceived: (err, res) ->
				if err
					Router.go 'login'
	, if config.GSM then 180000 else 60000

	# Переустановка токена при коннекте (и реконнекте)
	Tracker.autorun (c) ->
		status = Meteor.status()
		if status.connected
			token = Meteor._localStorage.getItem 'Meteor.loginToken'
			if token
				Meteor.apply 'extendToken', [token]
