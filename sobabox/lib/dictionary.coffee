@Dictionary =
	get: (key) -> @content[key]
	keys: -> _.keys(@content)
	count: -> @keys().length

	title: (key, labelKey = "title") ->
		obj = @get(key)
		if _.isString(obj) then obj else obj[labelKey]

	# Может принимать функцию или строку для получения label, если строка — это ключ элемента словаря, если функция —
	# в нее передается весь элемент.
	options: (labelKey = "title") ->

		resolver = (key) => if _.isString(labelKey) then @title(key, labelKey) else labelKey(@get(key))
		({label: resolver(key), value: key} for key in @keys())

	which: (array) -> (_.extend({enabled: array and key in array}, @get(key)) for key in @keys())
	extend: (key, objs...) -> _.extend @get(key), objs...
