This is a limited excerpt from 'Robonect' code.

Robonect is a device (and software) that provides you with means to monitor, remote control and configure various things in corporate network. It has a battery, gsm module, ethernet and wifi, ARM processor and some storage, many sensors (such as light and noise) and so on, and it fits in a box not much bigger than pack of cigarettes.

It's capable (provided by my software) of:

	- collecting user-defined metrics
	- aggregating this data according to different timespans and filters
	- presenting this data as live charts
	- watching for user-defined triggers and acting on them
	- making complex user-defined actions on the network, including using of ssh and telnet connections, COM-ports
	- configuring network routes, inspecting raw packets of data, logging of various information and so on.

Frontend of this product is written with Meteor (my framework of choice), running on Node.js. Other technologies include: influxDb, redis, mongodb, ngrok, semantic ui, stylus, jade, c3.js and other libraries, protocols and programs.

You can have a look on live instance at http://81.25.58.34:50080, login "admin", password "WebAdmin"
