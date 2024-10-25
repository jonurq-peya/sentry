import React, {useState} from 'react';
import styled from '@emotion/styled';
import isEqual from 'lodash/isEqual';

import AvatarList from 'sentry/components/avatar/avatarList';
import TeamAvatar from 'sentry/components/avatar/teamAvatar';
import Badge from 'sentry/components/badge/badge';
import {CompactSelect} from 'sentry/components/compactSelect';
import {CheckWrap} from 'sentry/components/compactSelect/styles';
import UserBadge from 'sentry/components/idBadge/userBadge';
import {InnerWrap, LeadingItems} from 'sentry/components/menuListItem';
import {Tooltip} from 'sentry/components/tooltip';
import {t} from 'sentry/locale';
import type {Team} from 'sentry/types/organization';
import type {User} from 'sentry/types/user';
import {useTeamsById} from 'sentry/utils/useTeamsById';
import {useUser} from 'sentry/utils/useUser';
import type {DashboardDetails, DashboardPermissions} from 'sentry/views/dashboards/types';

interface EditAccessSelectorProps {
  dashboard: DashboardDetails;
  onChangeEditAccess: (newDashboardPermissions?: DashboardPermissions) => void;
}

/**
 * Dropdown multiselect button to enable selective Dashboard editing access to
 * specific users and teams
 */
function EditAccessSelector({dashboard, onChangeEditAccess}: EditAccessSelectorProps) {
  const currentUser: User = useUser();
  const dashboardCreator: User | undefined = dashboard.createdBy;
  const {teams} = useTeamsById();
  const teamIds: string[] = Object.values(teams).map(team => team.id);

  const [newDashboardPermissions, setNewDashboardPermissions] = useState<
    DashboardPermissions | undefined
  >(dashboard.permissions ? structuredClone(dashboard.permissions) : undefined);

  const [selectedOptions, setselectedOptions] = useState<string[]>(
    dashboard.permissions?.isCreatorOnlyEditable
      ? ['_creator']
      : ['_everyone', '_creator', ...teamIds]
  );

  let isEverythingSelected =
    selectedOptions.length === ['_everyone', '_creator', ...teamIds].length;

  // Dashboard creator option in the dropdown
  const makeCreatorOption = () => ({
    value: '_creator',
    label: (
      <UserBadge
        avatarSize={18}
        user={dashboardCreator}
        displayName={
          <StyledDisplayName>
            {dashboardCreator?.id === currentUser.id
              ? `You (${currentUser.email})`
              : dashboardCreator?.email || currentUser.email}
          </StyledDisplayName>
        }
        displayEmail="Creator"
      />
    ),
    disabled: dashboardCreator?.id !== currentUser.id,
    checkboxProps: {
      isDisabled: true,
    },
  });

  // Single team option in the dropdown [WIP]
  const makeTeamOption = (team: Team) => ({
    value: team.id,
    label: `#${team.slug}`,
    leadingItems: <TeamAvatar team={team} size={18} />,
  });

  // Avatars/Badges in the Edit Selector Button
  const triggerAvatars = isEverythingSelected ? (
    <StyledBadge text={'All'} />
  ) : (
    <StyledAvatarList key="avatar-list" users={[currentUser]} avatarSize={25} />
  );

  const dropdownOptions = [
    makeCreatorOption(),
    {
      value: '_everyone_section',
      options: [
        {
          value: '_everyone',
          label: 'Everyone',
          disabled: dashboardCreator?.id !== currentUser.id,
        },
      ],
    },
    // [WIP: Selective edit access to teams]
    {
      value: '_teams',
      label: t('Teams'),
      options: teams.map(makeTeamOption),
      showToggleAllButton: true,
      disabled: true,
    },
  ];

  // Handles state change when dropdown options are selected
  const onSelectOptions = newSelectedOptions => {
    const newSelectedValues = newSelectedOptions.map(
      (option: {value: string}) => option.value
    );
    isEverythingSelected = false;
    if (newSelectedValues.includes('_everyone')) {
      isEverythingSelected = true;
      setselectedOptions(['_everyone', '_creator', ...teamIds]);
      if (newDashboardPermissions) {
        newDashboardPermissions.isCreatorOnlyEditable = false;
      }
    } else if (!newSelectedValues.includes('_everyone')) {
      setselectedOptions(['_creator']);
      if (newDashboardPermissions === undefined) {
        // When the dashboard does not have a permissions model associated
        setNewDashboardPermissions({isCreatorOnlyEditable: true});
      } else {
        newDashboardPermissions.isCreatorOnlyEditable = true;
      }
    }
  };

  const dropdownMenu = (
    <StyledCompactSelect
      size="sm"
      onChange={newSelectedOptions => {
        onSelectOptions(newSelectedOptions);
      }}
      onClose={() => {
        if (!isEqual(newDashboardPermissions, dashboard.permissions)) {
          onChangeEditAccess(newDashboardPermissions);
        }
      }}
      multiple
      searchable
      options={dropdownOptions}
      value={selectedOptions}
      triggerLabel={[
        <React.Fragment key="edit-access-label">{t('Edit Access:')}</React.Fragment>,
        <React.Fragment key="trigger-avatars">{triggerAvatars}</React.Fragment>,
      ]}
      searchPlaceholder="Search Teams"
      disableSearchFilter
    />
  );

  return dashboardCreator?.id !== currentUser.id ? (
    <Tooltip title={'Only Dashboard Creator may change Edit Access'}>
      {dropdownMenu}
    </Tooltip>
  ) : (
    dropdownMenu
  );
}

export default EditAccessSelector;

const StyledCompactSelect = styled(CompactSelect)`
  ${InnerWrap} {
    align-items: center;
  }

  ${LeadingItems} {
    margin-top: 0;
  }

  ${CheckWrap} {
    padding-bottom: 0;
  }
`;

const StyledDisplayName = styled('div')`
  font-weight: normal;
`;

const StyledAvatarList = styled(AvatarList)`
  margin-left: 10px;
`;

const StyledBadge = styled(Badge)`
  color: ${p => p.theme.white};
  background: ${p => p.theme.purple300};
  height: 22px;
  width: 22px;
  line-height: 22px;
  align-items: center;
  font-size: 100%;
  margin-right: 1px;
`;
