// synthetic source for the tests of the row tools: it is not MAME code

#include "emu.h"
#include "chipx.h"

#define LOG_CMD(...) LOGMASKED(LOG_COMMANDS, __VA_ARGS__)

void chipx_device::write(offs_t offset, uint8_t data)
{
	switch (offset)
	{
	case 0:
		if (data & 0x10)
		{
			begin_init(data);
		}
		else if (m_state == state_t::READY)
		{
			LOG_CMD("command %02x\n", data);
			if ((data & 0xe0) == 0xe0)
			{
				int level = data & 7;
				uint8_t mask = 1 << level;
				if (m_isr & mask)
				{
					m_isr &= ~mask;
					m_base = (level + 1) & 7;
				}
			}
		}
		break;

	case 1:
		m_imr = data;
		break;
	}
}

uint8_t chipx_device::read(offs_t offset)
{
	offset &= 3;
	if (offset == 2)
		return m_status;
	return 0;
}

TIMER_CALLBACK_MEMBER(chipx_device::tick)
{
	m_count = m_reload = param;
	chipx_irq(m_count == 0);
}

void chipx_device::start()
{
	m_timer->adjust(attotime::from_usec(10), 0, FUNC(chipx_device::tick));
}

void chipx_device::idle()
{
}
