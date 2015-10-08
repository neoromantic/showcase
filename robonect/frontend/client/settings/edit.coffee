# Шаблон формы редактирования объекта.
Template.settingsEdit.onRendered ->
	tpl = @

	@$('[name="tags"]').closest('.dropdown').dropdown
		fullTextSearch: true
		sortSelect: true
		action: 'select'
		onChange: (value, text, $selectedItem) ->
			tags = tpl.data.editDoc.tagsAsList()
			if text in tags
				tags = _.without tags, text
			else
				tags.push text
			tpl.data.editDoc.tags = tags.join(',')

# Для каждого типа объектов своя форма, здесь задаем название шаблона, в котором она лежит.
Template.settingsEdit.helpers
	objectForm: -> Router.current().params.model + "EditForm"
	modelName: -> Router.current().params.model
	hasTagsOrDescription: -> @editDoc?.tags or @editDoc?.description

Template.settingsEdit.events

	'keydown form': (ev) -> if ev.keyCode == 13 then ev.preventDefault()

	'keydown .basicInfoRow input.search': (ev, tpl) ->
		if ev.keyCode == 13
			tag = $(ev.currentTarget).val().trim()
			tags = tpl.data.editDoc.tagsAsList()
			if tag and tag not in tags
				tags.push tag
				tpl.data.editDoc.tags = tags.join(',')
				$(ev.currentTarget).val("")

	'click .basicInfoRow .button': (ev) ->
		$('.basicInfo').hide()
		$('.basicInfoRow .field').show()

	'click .button-delete-object': (ev, tpl) ->
		# Удаляем объект после того как скрылась форма, а то будет ерунда с ререндерингом шаблона.
		if confirm(TAPi18n.__("settings_common_delete_confirmation"))
			tpl.data.editDoc.delete()
			Router.go 'settingsList', model: Router.current().params.model

	'click .button-copy-object': (ev, tpl) ->
		obj = _.extend {}, tpl.data.editDoc._attr
		delete obj._id
		delete obj.id

		obj.title = obj.title + " (копия)"

		copyObj = tpl.data.editDoc.constructor.create obj
		copyObj.save()

		Router.go 'settingsEdit',
			model: Router.current().params.model
			slug: copyObj.slug()

	'click .objTag.label': (ev, tpl) ->
		tags = tpl.data.editDoc.tagsAsList()
		tags = _.without tags, $(ev.currentTarget).text().trim()
		tpl.data.editDoc.tags = tags.join(',')

	'change input[name], change select[name], change textarea[name]': (ev, tpl) ->
		name = $(ev.target).attr 'name'
		if name == 'tags' then return
		value = if $(ev.target).attr('type') == 'checkbox' then $(ev.target).is(':checked') else $(ev.target).val().trim()

		obj = tpl.data.editDoc
		if '.' in name
			tags = name.split '.'
			len = tags.length-1
			for tag in tags[0..len-1]
				obj = obj[tag]
			name = tags[len]

		obj[name] = value

	'submit form': (ev, tpl) ->
		ev.preventDefault()
		errors = tpl.data.editDoc.save()
		if not _.isEmpty errors
			tpl.$('.error').removeClass('error')
			for field, message of errors
				$('[name="'+field+'"]').closest('.field').addClass('error')
			$('.pageContent').scrollTo('.field.error:first')

		else
			Router.go 'settingsList', model: Router.current().params.model
