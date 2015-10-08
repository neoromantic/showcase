# На каждом переходе по роутам проверяем авторизацию. Если активной сессии нет — редиректим на форму логина
# Главная задача этой штуки — поставить userId, если он не стоит

if Meteor.isClient
	Router.onAfterAction (request, response) ->
		token = Meteor._localStorage.getItem 'Meteor.loginToken'
		if token
			Meteor.apply 'extendToken', [token], onResultReceived: (err, res) =>
				if err
					Meteor._localStorage.removeItem 'Meteor.loginToken'
					Router.go 'login'
		else
			Router.go 'login'
	, except: ['login', 'lockScreen']

	Meteor.startup -> resetToken()

	originalSetItem = Meteor._localStorage.setItem
	Meteor._localStorage.setItem = (key, value) ->
		if key == 'Meteor.loginToken'
			Meteor.defer resetToken
		originalSetItem.call Meteor._localStorage, key, value

	originalRemoveItem = Meteor._localStorage.removeItem
	Meteor._localStorage.removeItem = (key) ->
		if key == 'Meteor.loginToken'
			Meteor.defer resetToken
		originalRemoveItem.call Meteor._localStorage, key

	resetToken = ->
		loginToken = Meteor._localStorage.getItem 'Meteor.loginToken'

		if loginToken
			setToken(loginToken, new Date('2040/01/01'))
		else
			setToken(null, -1);

	setToken = (loginToken, expires) ->
		Cookie.set 'meteor_login_token', loginToken,
			path: '/'
			expires: expires

if Meteor.isServer
	Router.onBeforeAction (request, response) ->
		token = request.query.auth_token
		if redisCollection.matching("robonect:sessions:" + token).count() == 0
			response.writeHead(401, {"Content-Type": "text/plain"})
			response.end("Token is not valid")
		else
			@next()
	, only: ['login']
